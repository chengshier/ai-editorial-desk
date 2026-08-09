from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from packages.ai_gateway.domain import GatewayStructuredResult, InvocationContext
from packages.ai_gateway.errors import AIGatewayError
from packages.ai_gateway.gateway import AIGateway
from packages.connector_management.exceptions import (
    ConnectorManagementError,
    ResourceNotFoundError,
)
from packages.connector_management.repositories import AuditLogRepository
from packages.database.models import (
    AIInvocationRecord,
    DraftCitationUsage,
    DraftClaimReferenceRecord,
    DraftGenerationMode,
    DraftGenerationRunRecord,
    DraftGenerationStatus,
    DraftSourceType,
    DraftStatus,
    DraftType,
    EditorialDraftRecord,
    EditorialPackRecord,
    EditorialRecommendedFormat,
    EditorialRiskLevel,
    EventCardRecord,
    EventRecord,
    EventTrendSnapshotRecord,
    EvidenceClaimRecord,
    EvidenceVerificationState,
)
from packages.database.session import get_async_sessionmaker
from packages.database.types import utc_now
from packages.editorial.domain import normalize_text, stable_hash
from packages.editorial.drafts_context import (
    DraftGenerationInputBuilder,
    DraftGenerationSnapshot,
    EditorialContext,
    load_editorial_context,
)
from packages.editorial.drafts_domain import (
    DRAFT_PROMPT_VERSION,
    DRAFT_SCHEMA_NAME,
    DRAFT_SCHEMA_V1,
    DRAFT_SCHEMA_VERSION,
    EDITORIAL_PACK_VERSION,
    EVENT_CARD_VERSION,
    MAX_CARD_TIMELINE_ITEMS,
    MAX_MEDIA_ITEMS_PER_SIGNAL,
    MAX_PACK_MATERIAL_ITEMS,
    MAX_PACK_SOURCE_ITEMS,
    MAX_SUGGESTED_ANGLES,
    SAFE_MEDIA_METADATA_KEYS,
    ValidatedDraftCandidate,
    allowed_usages,
    draft_duration_seconds,
    draft_hard_max_chars,
    validate_draft_candidate,
)
from packages.editorial.drafts_repositories import (
    DraftClaimReferenceRepository,
    DraftGenerationRunRepository,
    EditorialDraftRepository,
    EditorialPackRepository,
    EventCardRepository,
)
from packages.editorial.errors import (
    DraftGenerationInProgressError,
    DraftRiskGateError,
    DraftValidationError,
    StaleEditorialContextError,
    UnsafeDraftClaimUsageError,
    UnsupportedDraftClaimError,
    UnsupportedDraftUnknownError,
)


class StructuredGateway(Protocol):
    async def generate_structured(
        self,
        *,
        task_key: str,
        messages: tuple[Any, ...],
        schema: dict[str, Any],
        schema_name: str,
        max_output_tokens: int | None = None,
        temperature: float | None = None,
        context: InvocationContext | None = None,
        invocation_id: UUID | None = None,
    ) -> GatewayStructuredResult: ...


@dataclass(frozen=True, slots=True)
class ArtifactCreationOutcome:
    artifact: EventCardRecord | EditorialPackRecord
    created: bool


@dataclass(frozen=True, slots=True)
class HumanDraftReference:
    claim_id: UUID
    section_key: str
    usage: DraftCitationUsage


@dataclass(frozen=True, slots=True)
class DraftGenerationOutcome:
    run_id: UUID | None
    ai_invocation_id: UUID | None
    mode: DraftGenerationMode
    status: DraftGenerationStatus
    draft: EditorialDraftRecord | None
    candidate: ValidatedDraftCandidate | None
    reused: bool


class EventCardService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self.session_factory = session_factory or get_async_sessionmaker()

    async def create(
        self,
        *,
        event_id: UUID,
        trend_snapshot_id: UUID | None = None,
    ) -> tuple[EventCardRecord, bool]:
        async with self.session_factory() as session:
            async with session.begin():
                context = await load_editorial_context(
                    session,
                    event_id,
                    for_update=True,
                )
                trend = await _select_trend(session, event_id, trend_snapshot_id)
                groups = _claim_groups(context)
                timeline = _timeline(context)[:MAX_CARD_TIMELINE_ITEMS]
                effective = {
                    "score_id": str(context.effective.base_score.id),
                    "context_hash": context.effective.context_hash,
                    "override_ids": [
                        str(item.id) for item in context.effective.overrides
                    ],
                    "values": context.effective.values,
                }
                input_hash = stable_hash(
                    {
                        "card_version": EVENT_CARD_VERSION,
                        "event": {
                            "id": str(context.event.id),
                            "status": context.event.status.value,
                            "last_updated_at": context.event.last_updated_at,
                            "title": context.event.title,
                            "category": context.event.category,
                        },
                        "editorial_context_hash": context.context_hash,
                        "evidence_snapshot_hash": context.evidence.snapshot_hash,
                        "trend_snapshot_id": str(trend.id) if trend else None,
                        "trend_input_hash": trend.input_hash if trend else None,
                        "effective_context_hash": context.effective.context_hash,
                    }
                )
                return await EventCardRepository(session).insert_if_absent(
                    {
                        "event_id": event_id,
                        "card_version": EVENT_CARD_VERSION,
                        "evidence_snapshot_hash": context.evidence.snapshot_hash,
                        "trend_snapshot_id": trend.id if trend else None,
                        "editorial_score_id": context.effective.base_score.id,
                        "title": context.event.title,
                        "concise_summary": _concise_summary(context),
                        "timeline": timeline,
                        "confirmed_claim_ids": groups["confirmed"],
                        "investigating_claim_ids": groups["investigating"],
                        "single_source_claim_ids": groups["single_source"],
                        "disputed_claim_ids": groups["disputed"],
                        "false_claim_ids": groups["false"],
                        "unknown_ids": [
                            str(item.id)
                            for item in context.evidence.unknowns
                            if item.status.value == "open"
                        ],
                        "source_summary": {
                            "signal_count": len(context.memberships),
                            "source_count": context.event.source_count,
                            "platform_count": context.event.platform_count,
                            "timeline_item_count": len(timeline),
                            "timeline_truncated": (
                                len(context.memberships) > len(timeline)
                            ),
                        },
                        "effective_assessment": effective,
                        "risk_level": context.effective.risk_level,
                        "recommended_format": (
                            context.effective.recommended_format
                        ),
                        "generated_by": "deterministic",
                        "ai_invocation_id": None,
                        "input_hash": input_hash,
                    }
                )

    async def list(self, event_id: UUID) -> tuple[EventCardRecord, ...]:
        async with self.session_factory() as session:
            if await session.get(EventRecord, event_id) is None:
                raise ResourceNotFoundError("事件不存在")
            return tuple(await EventCardRepository(session).list_for_event(event_id))


class EditorialPackService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self.session_factory = session_factory or get_async_sessionmaker()

    async def create(
        self,
        *,
        event_id: UUID,
        event_card_id: UUID,
    ) -> tuple[EditorialPackRecord, bool]:
        async with self.session_factory() as session:
            async with session.begin():
                context = await load_editorial_context(
                    session,
                    event_id,
                    for_update=True,
                )
                card = await session.get(EventCardRecord, event_card_id)
                if card is None or card.event_id != event_id:
                    raise ResourceNotFoundError("Event Card不存在")
                _assert_card_current(card, context)

                source_items = _source_items(context)[:MAX_PACK_SOURCE_ITEMS]
                material_items, media_warnings = _material_items(context)
                material_items = material_items[:MAX_PACK_MATERIAL_ITEMS]
                unknown_items = [
                    {
                        "unknown_id": str(item.id),
                        "text": item.unknown_text,
                        "status": item.status.value,
                    }
                    for item in context.evidence.unknowns
                    if item.status.value == "open"
                ]
                claim_references = _claim_reference_items(context)
                warnings = _pack_warnings(context) + media_warnings
                angles = _suggested_angles(context)[:MAX_SUGGESTED_ANGLES]
                input_hash = stable_hash(
                    {
                        "event_id": str(event_id),
                        "event_card_id": str(card.id),
                        "card_input_hash": card.input_hash,
                        "pack_version": EDITORIAL_PACK_VERSION,
                        "recommended_format": card.recommended_format.value,
                        "source_items": source_items,
                        "material_items": material_items,
                        "warnings": warnings,
                        "unknown_items": unknown_items,
                        "claim_references": claim_references,
                        "suggested_angles": angles,
                    }
                )
                return await EditorialPackRepository(session).insert_if_absent(
                    {
                        "event_id": event_id,
                        "event_card_id": card.id,
                        "pack_version": EDITORIAL_PACK_VERSION,
                        "recommended_format": card.recommended_format,
                        "suggested_angles": angles,
                        "source_items": source_items,
                        "timeline_items": card.timeline,
                        "material_items": material_items,
                        "warnings": warnings,
                        "unknown_items": unknown_items,
                        "claim_references": claim_references,
                        "input_hash": input_hash,
                        "ai_invocation_id": None,
                    }
                )

    async def list(self, event_id: UUID) -> tuple[EditorialPackRecord, ...]:
        async with self.session_factory() as session:
            if await session.get(EventRecord, event_id) is None:
                raise ResourceNotFoundError("事件不存在")
            return tuple(
                await EditorialPackRepository(session).list_for_event(event_id)
            )


class DraftService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        gateway: StructuredGateway | None = None,
    ) -> None:
        self.session_factory = session_factory or get_async_sessionmaker()
        self.gateway = gateway or AIGateway(session_factory=self.session_factory)
        self.input_builder = DraftGenerationInputBuilder(self.session_factory)

    async def generate(
        self,
        *,
        event_id: UUID,
        event_card_id: UUID,
        editorial_pack_id: UUID,
        draft_type: DraftType,
        actor: str,
        apply: bool,
        risk_approval_reason: str | None = None,
    ) -> DraftGenerationOutcome:
        actor = _require_actor(actor)
        snapshot = await self.input_builder.build(
            event_id=event_id,
            event_card_id=event_card_id,
            editorial_pack_id=editorial_pack_id,
            draft_type=draft_type,
        )
        _enforce_risk_gate(
            snapshot,
            apply=apply,
            approval_reason=risk_approval_reason,
        )
        mode = DraftGenerationMode.APPLY if apply else DraftGenerationMode.PREVIEW

        if apply:
            existing = await self._existing_ai(snapshot)
            if existing is not None:
                return _reused_outcome(existing)

        run, created = await self._start_run(snapshot, actor=actor, mode=mode)
        if apply and not created:
            if run.status is DraftGenerationStatus.RUNNING:
                raise DraftGenerationInProgressError(
                    "相同Draft输入已有Worker正在生成"
                )
            existing = await self._existing_ai(snapshot)
            if existing is not None:
                return _reused_outcome(existing)
            raise DraftValidationError(
                "相同Draft输入已有失败Run；需重新生成Card/Pack或调整上下文后重试"
            )

        if (
            apply
            and snapshot.risk_level is EditorialRiskLevel.R3
            and normalize_text(risk_approval_reason or "")
        ):
            await self._audit_risk_approval(
                run_id=run.id,
                event_id=event_id,
                actor=actor,
                reason=risk_approval_reason or "",
            )

        invocation_id = uuid4()
        try:
            result = await self.gateway.generate_structured(
                task_key="draft_generation",
                messages=snapshot.messages(),
                schema=DRAFT_SCHEMA_V1,
                schema_name=DRAFT_SCHEMA_NAME,
                max_output_tokens=6000,
                temperature=0.2,
                context=InvocationContext(
                    prompt_version=DRAFT_PROMPT_VERSION,
                    schema_version=DRAFT_SCHEMA_VERSION,
                    subject_type="event",
                    subject_id=str(event_id),
                    metadata={
                        "draft_generation_run_id": str(run.id),
                        "event_card_id": str(event_card_id),
                        "editorial_pack_id": str(editorial_pack_id),
                        "draft_type": draft_type.value,
                    },
                ),
                invocation_id=invocation_id,
            )
        except AIGatewayError as exc:
            await self._finish_failed(
                run.id,
                invocation_id,
                exc.code.value,
                exc.message,
            )
            raise

        try:
            candidate = validate_draft_candidate(result.data)
            _validate_candidate_against_snapshot(candidate, snapshot)
        except ValueError as exc:
            await self._finish_failed(
                run.id,
                result.invocation_id,
                "DRAFT_OUTPUT_INVALID",
                str(exc),
            )
            raise DraftValidationError(str(exc)) from exc
        except ConnectorManagementError as exc:
            await self._finish_failed(
                run.id,
                result.invocation_id,
                exc.code,
                exc.message,
            )
            raise

        if not apply:
            await self._finish_success(run.id, result.invocation_id)
            return DraftGenerationOutcome(
                run_id=run.id,
                ai_invocation_id=result.invocation_id,
                mode=mode,
                status=DraftGenerationStatus.SUCCEEDED,
                draft=None,
                candidate=candidate,
                reused=False,
            )

        try:
            draft, draft_created = await self._apply_ai_draft(
                run_id=run.id,
                invocation_id=result.invocation_id,
                snapshot=snapshot,
                candidate=candidate,
                actor=actor,
            )
        except ConnectorManagementError as exc:
            await self._finish_failed(
                run.id,
                result.invocation_id,
                exc.code,
                exc.message,
            )
            raise

        return DraftGenerationOutcome(
            run_id=run.id,
            ai_invocation_id=result.invocation_id,
            mode=mode,
            status=DraftGenerationStatus.SUCCEEDED,
            draft=draft,
            candidate=candidate,
            reused=not draft_created,
        )

    async def create_manual(
        self,
        *,
        event_id: UUID,
        event_card_id: UUID,
        editorial_pack_id: UUID,
        draft_type: DraftType,
        actor: str,
        reason: str,
        body: str,
        references: Sequence[HumanDraftReference],
        title: str | None = None,
        hook: str | None = None,
        ending: str | None = None,
        interaction_question: str | None = None,
    ) -> EditorialDraftRecord:
        actor = _require_actor(actor)
        reason = _require_note(reason, "Human Draft reason")
        body = _bounded_body(body, draft_type)
        if not references:
            raise DraftValidationError("Human Draft至少需要一个Claim reference")

        async with self.session_factory() as session:
            async with session.begin():
                context = await load_editorial_context(
                    session,
                    event_id,
                    for_update=True,
                )
                card, pack = await _require_card_pack(
                    session,
                    event_id,
                    event_card_id,
                    editorial_pack_id,
                )
                _assert_card_current(card, context)
                normalized_refs = _validate_human_references(references, context)
                draft_id = uuid4()
                input_hash = stable_hash(
                    {
                        "source_type": "human",
                        "event_id": str(event_id),
                        "card_id": str(card.id),
                        "pack_id": str(pack.id),
                        "context_hash": context.context_hash,
                        "draft_type": draft_type.value,
                        "body": body,
                        "references": [
                            (
                                str(item.claim_id),
                                item.section_key,
                                item.usage.value,
                            )
                            for item in normalized_refs
                        ],
                        "reason": reason,
                    }
                )
                draft = EditorialDraftRecord(
                    id=draft_id,
                    event_id=event_id,
                    event_card_id=card.id,
                    editorial_pack_id=pack.id,
                    draft_chain_id=draft_id,
                    draft_type=draft_type,
                    format_key=context.effective.recommended_format,
                    duration_target_seconds=draft_duration_seconds(draft_type),
                    language=context.event.primary_language or "zh-CN",
                    draft_version=1,
                    parent_draft_id=None,
                    source_type=DraftSourceType.HUMAN,
                    status=DraftStatus.EDITED,
                    title=_optional(title),
                    title_candidates=_candidate_list(title),
                    hook=_optional(hook),
                    hook_candidates=_candidate_list(hook),
                    cover_text_candidates=[],
                    sections=[],
                    body=body,
                    ending=_optional(ending),
                    interaction_question=_optional(interaction_question),
                    prompt_version=None,
                    schema_version=None,
                    ai_invocation_id=None,
                    generation_run_id=None,
                    input_hash=input_hash,
                    created_by_actor=actor,
                    change_note=reason,
                )
                EditorialDraftRepository(session).add_human(draft)
                await session.flush()
                _add_reference_rows(session, draft.id, normalized_refs)
                AuditLogRepository(session).add(
                    entity_type="editorial_draft",
                    entity_id=draft.id,
                    action="human_create",
                    actor=actor,
                    before_data={},
                    after_data={
                        "event_id": str(event_id),
                        "draft_type": draft_type.value,
                        "draft_version": 1,
                        "risk_level": context.effective.risk_level.value,
                        "reason": reason,
                    },
                )
                return draft

    async def revise(
        self,
        *,
        event_id: UUID,
        parent_draft_id: UUID,
        actor: str,
        change_note: str,
        body: str,
        references: Sequence[HumanDraftReference],
        title: str | None = None,
        hook: str | None = None,
        ending: str | None = None,
        interaction_question: str | None = None,
    ) -> EditorialDraftRecord:
        actor = _require_actor(actor)
        change_note = _require_note(change_note, "Revision change_note")
        if not references:
            raise DraftValidationError("Human Revision至少需要一个Claim reference")

        async with self.session_factory() as session:
            async with session.begin():
                context = await load_editorial_context(
                    session,
                    event_id,
                    for_update=True,
                )
                repo = EditorialDraftRepository(session)
                parent = await repo.get_for_update(parent_draft_id)
                if parent is None or parent.event_id != event_id:
                    raise ResourceNotFoundError("Parent Draft不存在")
                body = _bounded_body(body, parent.draft_type)
                latest_version = await repo.max_chain_version(parent.draft_chain_id)
                if latest_version != parent.draft_version:
                    raise DraftValidationError(
                        "只能基于当前chain最新Draft创建Revision"
                    )
                normalized_refs = _validate_human_references(references, context)
                new_version = latest_version + 1
                input_hash = stable_hash(
                    {
                        "source_type": "human_revision",
                        "parent_draft_id": str(parent.id),
                        "draft_chain_id": str(parent.draft_chain_id),
                        "draft_version": new_version,
                        "context_hash": context.context_hash,
                        "body": body,
                        "references": [
                            (
                                str(item.claim_id),
                                item.section_key,
                                item.usage.value,
                            )
                            for item in normalized_refs
                        ],
                        "change_note": change_note,
                    }
                )
                draft = EditorialDraftRecord(
                    event_id=event_id,
                    event_card_id=parent.event_card_id,
                    editorial_pack_id=parent.editorial_pack_id,
                    draft_chain_id=parent.draft_chain_id,
                    draft_type=parent.draft_type,
                    format_key=parent.format_key,
                    duration_target_seconds=parent.duration_target_seconds,
                    language=parent.language,
                    draft_version=new_version,
                    parent_draft_id=parent.id,
                    source_type=DraftSourceType.HUMAN,
                    status=DraftStatus.EDITED,
                    title=_inherit_optional(title, parent.title),
                    title_candidates=[],
                    hook=_inherit_optional(hook, parent.hook),
                    hook_candidates=[],
                    cover_text_candidates=[],
                    sections=[],
                    body=body,
                    ending=_inherit_optional(ending, parent.ending),
                    interaction_question=_inherit_optional(
                        interaction_question,
                        parent.interaction_question,
                    ),
                    prompt_version=None,
                    schema_version=None,
                    ai_invocation_id=None,
                    generation_run_id=None,
                    input_hash=input_hash,
                    created_by_actor=actor,
                    change_note=change_note,
                )
                repo.add_human(draft)
                await session.flush()
                _add_reference_rows(session, draft.id, normalized_refs)
                AuditLogRepository(session).add(
                    entity_type="editorial_draft",
                    entity_id=draft.id,
                    action="human_revision",
                    actor=actor,
                    before_data={
                        "parent_draft_id": str(parent.id),
                        "draft_version": parent.draft_version,
                    },
                    after_data={
                        "draft_version": new_version,
                        "change_note": change_note,
                    },
                )
                return draft

    async def list(self, event_id: UUID) -> tuple[EditorialDraftRecord, ...]:
        async with self.session_factory() as session:
            if await session.get(EventRecord, event_id) is None:
                raise ResourceNotFoundError("事件不存在")
            return tuple(await EditorialDraftRepository(session).list_for_event(event_id))

    async def detail(
        self,
        event_id: UUID,
        draft_id: UUID,
    ) -> tuple[EditorialDraftRecord, tuple[DraftClaimReferenceRecord, ...]]:
        async with self.session_factory() as session:
            draft = await session.get(EditorialDraftRecord, draft_id)
            if draft is None or draft.event_id != event_id:
                raise ResourceNotFoundError("Draft不存在")
            refs = await DraftClaimReferenceRepository(session).list_for_draft(draft.id)
            return draft, tuple(refs)

    async def chain(
        self,
        event_id: UUID,
        draft_id: UUID,
    ) -> tuple[EditorialDraftRecord, ...]:
        async with self.session_factory() as session:
            draft = await session.get(EditorialDraftRecord, draft_id)
            if draft is None or draft.event_id != event_id:
                raise ResourceNotFoundError("Draft不存在")
            return tuple(
                await EditorialDraftRepository(session).list_chain(
                    draft.draft_chain_id
                )
            )

    async def _existing_ai(
        self,
        snapshot: DraftGenerationSnapshot,
    ) -> EditorialDraftRecord | None:
        async with self.session_factory() as session:
            return await EditorialDraftRepository(session).get_ai_by_input(
                event_card_id=snapshot.event_card_id,
                editorial_pack_id=snapshot.editorial_pack_id,
                draft_type=snapshot.draft_type,
                prompt_version=DRAFT_PROMPT_VERSION,
                schema_version=DRAFT_SCHEMA_VERSION,
                input_hash=snapshot.input_hash,
            )

    async def _start_run(
        self,
        snapshot: DraftGenerationSnapshot,
        *,
        actor: str,
        mode: DraftGenerationMode,
    ) -> tuple[DraftGenerationRunRecord, bool]:
        values: dict[str, object] = {
            "event_id": snapshot.event_id,
            "event_card_id": snapshot.event_card_id,
            "editorial_pack_id": snapshot.editorial_pack_id,
            "ai_invocation_id": None,
            "draft_type": snapshot.draft_type,
            "prompt_version": DRAFT_PROMPT_VERSION,
            "schema_version": DRAFT_SCHEMA_VERSION,
            "mode": mode,
            "status": DraftGenerationStatus.RUNNING,
            "input_hash": snapshot.input_hash,
            "requested_by": actor,
            "error_code": None,
            "error_summary": None,
            "finished_at": None,
        }
        async with self.session_factory() as session:
            async with session.begin():
                repo = DraftGenerationRunRepository(session)
                if mode is DraftGenerationMode.APPLY:
                    return await repo.claim_apply(values)
                run = DraftGenerationRunRecord(**values)  # type: ignore[arg-type]
                repo.add(run)
                await session.flush()
                return run, True

    async def _apply_ai_draft(
        self,
        *,
        run_id: UUID,
        invocation_id: UUID,
        snapshot: DraftGenerationSnapshot,
        candidate: ValidatedDraftCandidate,
        actor: str,
    ) -> tuple[EditorialDraftRecord, bool]:
        async with self.session_factory() as session:
            async with session.begin():
                context = await load_editorial_context(
                    session,
                    snapshot.event_id,
                    for_update=True,
                )
                if context.context_hash != snapshot.context_hash:
                    raise StaleEditorialContextError(
                        "Draft生成期间Evidence、Event或Effective Editorial Assessment已变化"
                    )
                card, _pack = await _require_card_pack(
                    session,
                    snapshot.event_id,
                    snapshot.event_card_id,
                    snapshot.editorial_pack_id,
                )
                _assert_card_current(card, context)
                _validate_candidate_against_context(candidate, context)
                run = await DraftGenerationRunRepository(session).get_for_update(run_id)
                if run is None:
                    raise RuntimeError("Draft Generation Run不存在")

                draft_id = uuid4()
                draft, created = await EditorialDraftRepository(
                    session
                ).insert_ai_if_absent(
                    {
                        "id": draft_id,
                        "event_id": snapshot.event_id,
                        "event_card_id": snapshot.event_card_id,
                        "editorial_pack_id": snapshot.editorial_pack_id,
                        "draft_chain_id": draft_id,
                        "draft_type": snapshot.draft_type,
                        "format_key": snapshot.format_key,
                        "duration_target_seconds": (
                            snapshot.duration_target_seconds
                        ),
                        "language": context.event.primary_language or "zh-CN",
                        "draft_version": 1,
                        "parent_draft_id": None,
                        "source_type": DraftSourceType.AI,
                        "status": DraftStatus.GENERATED,
                        "title": candidate.title_candidates[0],
                        "title_candidates": list(candidate.title_candidates),
                        "hook": candidate.hook_candidates[0],
                        "hook_candidates": list(candidate.hook_candidates),
                        "cover_text_candidates": list(
                            candidate.cover_text_candidates
                        ),
                        "sections": _serialize_sections(candidate),
                        "body": candidate.body_text(),
                        "ending": candidate.ending,
                        "interaction_question": candidate.interaction_question,
                        "prompt_version": DRAFT_PROMPT_VERSION,
                        "schema_version": DRAFT_SCHEMA_VERSION,
                        "ai_invocation_id": invocation_id,
                        "generation_run_id": run_id,
                        "input_hash": snapshot.input_hash,
                        "created_by_actor": actor,
                        "change_note": None,
                    }
                )
                if created:
                    for section in candidate.sections:
                        for citation in section.citations:
                            DraftClaimReferenceRepository(session).add(
                                DraftClaimReferenceRecord(
                                    draft_id=draft.id,
                                    claim_id=citation.claim_id,
                                    section_key=section.section_key,
                                    usage=citation.usage,
                                )
                            )
                run.ai_invocation_id = invocation_id
                run.status = DraftGenerationStatus.SUCCEEDED
                run.finished_at = utc_now()
                await session.flush()
                return draft, created

    async def _finish_success(self, run_id: UUID, invocation_id: UUID) -> None:
        async with self.session_factory() as session:
            async with session.begin():
                run = await DraftGenerationRunRepository(session).get_for_update(run_id)
                if run is None:
                    raise RuntimeError("Draft Generation Run不存在")
                run.ai_invocation_id = invocation_id
                run.status = DraftGenerationStatus.SUCCEEDED
                run.finished_at = utc_now()

    async def _finish_failed(
        self,
        run_id: UUID,
        invocation_id: UUID,
        error_code: str,
        error_summary: str,
    ) -> None:
        async with self.session_factory() as session:
            async with session.begin():
                run = await DraftGenerationRunRepository(session).get_for_update(run_id)
                if run is None:
                    return
                invocation = await session.get(AIInvocationRecord, invocation_id)
                run.ai_invocation_id = invocation_id if invocation is not None else None
                run.status = DraftGenerationStatus.FAILED
                run.error_code = error_code[:100]
                run.error_summary = normalize_text(error_summary)[:500]
                run.finished_at = utc_now()

    async def _audit_risk_approval(
        self,
        *,
        run_id: UUID,
        event_id: UUID,
        actor: str,
        reason: str,
    ) -> None:
        reason = _require_note(reason, "risk approval reason")
        async with self.session_factory() as session:
            async with session.begin():
                AuditLogRepository(session).add(
                    entity_type="draft_generation_run",
                    entity_id=run_id,
                    action="human_risk_approval",
                    actor=actor,
                    before_data={},
                    after_data={
                        "event_id": str(event_id),
                        "risk_level": "R3",
                        "reason": reason,
                    },
                )


class EditorialMarkdownExporter:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self.session_factory = session_factory or get_async_sessionmaker()

    async def render(
        self,
        *,
        event_id: UUID,
        editorial_pack_id: UUID,
        draft_id: UUID | None = None,
    ) -> str:
        async with self.session_factory() as session:
            pack = await session.get(EditorialPackRecord, editorial_pack_id)
            if pack is None or pack.event_id != event_id:
                raise ResourceNotFoundError("Editorial Pack不存在")
            card = await session.get(EventCardRecord, pack.event_card_id)
            if card is None:
                raise ResourceNotFoundError("Event Card不存在")
            trend = None
            if card.trend_snapshot_id is not None:
                trend = await session.get(
                    EventTrendSnapshotRecord,
                    card.trend_snapshot_id,
                )
            claims = {
                item.id: item
                for item in (
                    await session.scalars(
                        select(EvidenceClaimRecord).where(
                            EvidenceClaimRecord.event_id == event_id
                        )
                    )
                ).all()
            }
            draft: EditorialDraftRecord | None = None
            refs: Sequence[DraftClaimReferenceRecord] = ()
            if draft_id is not None:
                draft = await session.get(EditorialDraftRecord, draft_id)
                if draft is None or draft.event_id != event_id:
                    raise ResourceNotFoundError("Draft不存在")
                refs = await DraftClaimReferenceRepository(
                    session
                ).list_for_draft(draft.id)

        values = card.effective_assessment.get("values", {})
        lines = [
            f"# Event\n\n{card.title}",
            "## Summary",
            card.concise_summary,
            "## Trend",
            _trend_markdown(trend),
            "## Editorial Score",
            (
                f"- traffic_total: {values.get('traffic_total', 'N/A')}\n"
                f"- score_id: {card.editorial_score_id}"
            ),
            "## Risk",
            (
                f"- risk_level: {card.risk_level.value}\n"
                f"- recommended_format: {card.recommended_format.value}"
            ),
            "## Claims",
            _claims_markdown(card, claims),
            "## Unknowns",
            _list_mapping(pack.unknown_items, "text"),
            "## Timeline",
            _timeline_markdown(pack.timeline_items),
            "## Sources",
            _sources_markdown(pack.source_items),
            "## Suggested Angles",
            _list_mapping(pack.suggested_angles, "text"),
            "## Material Checklist",
            _materials_markdown(pack.material_items, pack.warnings),
            "## Draft",
            _draft_markdown(draft, refs),
        ]
        return "\n\n".join(lines).strip() + "\n"


def _reused_outcome(draft: EditorialDraftRecord) -> DraftGenerationOutcome:
    return DraftGenerationOutcome(
        run_id=draft.generation_run_id,
        ai_invocation_id=draft.ai_invocation_id,
        mode=DraftGenerationMode.APPLY,
        status=DraftGenerationStatus.SUCCEEDED,
        draft=draft,
        candidate=None,
        reused=True,
    )


def _claim_groups(context: EditorialContext) -> dict[str, list[str]]:
    groups = {item.value: [] for item in EvidenceVerificationState}
    for claim in context.evidence.claims:
        groups[claim.verification_state.value].append(str(claim.id))
    return groups


def _concise_summary(context: EditorialContext) -> str:
    by_state = {state: [] for state in EvidenceVerificationState}
    for claim in context.evidence.claims:
        by_state[claim.verification_state].append(claim.claim_text)
    pieces: list[str] = []
    labels = (
        (EvidenceVerificationState.CONFIRMED, "已确认"),
        (EvidenceVerificationState.INVESTIGATING, "调查中"),
        (EvidenceVerificationState.SINGLE_SOURCE, "单一来源"),
        (EvidenceVerificationState.DISPUTED, "存在争议"),
        (EvidenceVerificationState.FALSE, "已证伪说法"),
    )
    for state, label in labels:
        if by_state[state]:
            pieces.append(f"{label}：{by_state[state][0]}")
        if len(pieces) >= 3:
            break
    if not pieces:
        return "当前尚无可用于资料卡的Evidence Claim。"
    return "；".join(pieces)


def _timeline(context: EditorialContext) -> list[dict[str, Any]]:
    items = [
        {
            "signal_id": str(signal.id),
            "relation": link.relation.value,
            "title": signal.title,
            "platform": signal.platform,
            "author_name": signal.author_name,
            "published_at": (
                signal.published_at.isoformat() if signal.published_at else None
            ),
            "collected_at": signal.collected_at.isoformat(),
            "original_url": signal.original_url,
            "canonical_url": signal.canonical_url,
        }
        for link, signal in context.memberships
    ]
    items.sort(
        key=lambda item: (
            item["published_at"] or item["collected_at"],
            item["signal_id"],
        )
    )
    return items


def _source_items(context: EditorialContext) -> list[dict[str, Any]]:
    return _timeline(context)


def _material_items(
    context: EditorialContext,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    claim_ids_by_signal: dict[UUID, list[str]] = {}
    claim_by_id = {item.id: item for item in context.evidence.claims}
    for link in context.evidence.source_links:
        claim_ids_by_signal.setdefault(link.signal_id, []).append(
            str(link.claim_id)
        )

    materials: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    for _event_link, signal in context.memberships:
        media_items = signal.media[:MAX_MEDIA_ITEMS_PER_SIGNAL]
        if not media_items:
            warnings.append(
                {
                    "code": "MEDIA_METADATA_UNAVAILABLE",
                    "signal_id": str(signal.id),
                    "message": (
                        "该Signal没有统一可验证的media metadata，请人工检查原链接。"
                    ),
                }
            )
            continue

        attached_claims = [
            claim_by_id[UUID(raw_id)]
            for raw_id in claim_ids_by_signal.get(signal.id, [])
            if UUID(raw_id) in claim_by_id
        ]
        risky = any(
            item.verification_state
            in (
                EvidenceVerificationState.DISPUTED,
                EvidenceVerificationState.FALSE,
            )
            for item in attached_claims
        )
        for media in media_items:
            metadata = {
                key: value
                for key, value in media.items()
                if key in SAFE_MEDIA_METADATA_KEYS
                and isinstance(value, (str, int, float, bool))
            }
            media_type = str(
                metadata.get("media_type")
                or metadata.get("type")
                or "unclassified"
            )[:50]
            materials.append(
                {
                    "signal_id": str(signal.id),
                    "media_type": media_type,
                    "source_url": signal.original_url,
                    "title": signal.title,
                    "available_metadata": metadata,
                    "usage_note": (
                        "metadata_only_no_download; review copyright/context before use"
                    ),
                    "claim_ids": claim_ids_by_signal.get(signal.id, []),
                    "risk_note": (
                        "verify_disputed_or_false_context"
                        if risky
                        else "manual_rights_review_required"
                    ),
                }
            )
    return materials, warnings


def _claim_reference_items(context: EditorialContext) -> list[dict[str, Any]]:
    source_counts: dict[UUID, int] = {}
    for link in context.evidence.source_links:
        source_counts[link.claim_id] = source_counts.get(link.claim_id, 0) + 1
    return [
        {
            "claim_id": str(item.id),
            "text": item.claim_text,
            "claim_type": item.claim_type.value,
            "verification_state": item.verification_state.value,
            "source_count": source_counts.get(item.id, 0),
        }
        for item in context.evidence.claims
    ]


def _pack_warnings(context: EditorialContext) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    for item in context.evidence.claims:
        if item.verification_state in (
            EvidenceVerificationState.SINGLE_SOURCE,
            EvidenceVerificationState.DISPUTED,
            EvidenceVerificationState.FALSE,
        ):
            warnings.append(
                {
                    "code": f"CLAIM_{item.verification_state.value.upper()}",
                    "claim_id": str(item.id),
                    "message": "表达时必须保留Evidence verification语义。",
                }
            )
    for item in context.evidence.unknowns:
        if item.status.value == "open":
            warnings.append(
                {
                    "code": "OPEN_UNKNOWN",
                    "unknown_id": str(item.id),
                    "message": item.unknown_text,
                }
            )
    return warnings


def _suggested_angles(context: EditorialContext) -> list[dict[str, Any]]:
    by_state = {state: [] for state in EvidenceVerificationState}
    for item in context.evidence.claims:
        by_state[item.verification_state].append(str(item.id))

    candidates: list[dict[str, Any]] = []
    confirmed = by_state[EvidenceVerificationState.CONFIRMED]
    if confirmed:
        candidates.append(
            {
                "key": "fact_timeline",
                "text": "围绕已确认事实做时间线还原",
                "claim_ids": confirmed[:5],
            }
        )
    fact_check_ids = (
        by_state[EvidenceVerificationState.FALSE]
        + by_state[EvidenceVerificationState.DISPUTED]
    )
    if fact_check_ids:
        candidates.append(
            {
                "key": "fact_check",
                "text": "围绕争议或已证伪说法做真假拆解",
                "claim_ids": fact_check_ids[:5],
            }
        )
    attributed = (
        by_state[EvidenceVerificationState.INVESTIGATING]
        + by_state[EvidenceVerificationState.SINGLE_SOURCE]
    )
    if attributed:
        candidates.append(
            {
                "key": "what_we_know",
                "text": "区分目前已知与仍待确认的信息",
                "claim_ids": attributed[:5],
            }
        )
    return candidates[:MAX_SUGGESTED_ANGLES]


async def _select_trend(
    session: AsyncSession,
    event_id: UUID,
    trend_snapshot_id: UUID | None,
) -> EventTrendSnapshotRecord | None:
    if trend_snapshot_id is not None:
        trend = await session.get(EventTrendSnapshotRecord, trend_snapshot_id)
        if trend is None or trend.event_id != event_id:
            raise ResourceNotFoundError("Trend Snapshot不存在")
        return trend
    statement = (
        select(EventTrendSnapshotRecord)
        .where(EventTrendSnapshotRecord.event_id == event_id)
        .order_by(
            EventTrendSnapshotRecord.window_end_at.desc(),
            EventTrendSnapshotRecord.created_at.desc(),
            EventTrendSnapshotRecord.id.desc(),
        )
        .limit(1)
    )
    return (await session.execute(statement)).scalar_one_or_none()


def _assert_card_current(card: EventCardRecord, context: EditorialContext) -> None:
    if card.evidence_snapshot_hash != context.evidence.snapshot_hash:
        raise StaleEditorialContextError(
            "Event Card的Evidence已变化，请生成新Card"
        )
    if card.editorial_score_id != context.effective.base_score.id:
        raise StaleEditorialContextError(
            "Event Card绑定的Effective Score已变化"
        )
    if card.effective_assessment.get("context_hash") != context.effective.context_hash:
        raise StaleEditorialContextError(
            "Event Card绑定的Human Override已变化"
        )


async def _require_card_pack(
    session: AsyncSession,
    event_id: UUID,
    event_card_id: UUID,
    editorial_pack_id: UUID,
) -> tuple[EventCardRecord, EditorialPackRecord]:
    card = await session.get(EventCardRecord, event_card_id)
    pack = await session.get(EditorialPackRecord, editorial_pack_id)
    if card is None or card.event_id != event_id:
        raise ResourceNotFoundError("Event Card不存在")
    if pack is None or pack.event_id != event_id or pack.event_card_id != card.id:
        raise ResourceNotFoundError("Editorial Pack不存在或不属于该Card")
    return card, pack


def _enforce_risk_gate(
    snapshot: DraftGenerationSnapshot,
    *,
    apply: bool,
    approval_reason: str | None,
) -> None:
    if not apply:
        return
    if snapshot.risk_level is EditorialRiskLevel.R4:
        if snapshot.format_key is not EditorialRecommendedFormat.FACT_CHECK:
            raise DraftRiskGateError(
                "R4只允许fact_check AI Draft Apply；Event不会因此被删除"
            )
        return
    safe_r3_formats = {
        EditorialRecommendedFormat.FACT_CHECK,
        EditorialRecommendedFormat.QUICK_EXPLAINER,
    }
    if (
        snapshot.risk_level is EditorialRiskLevel.R3
        and snapshot.format_key not in safe_r3_formats
        and not normalize_text(approval_reason or "")
    ):
        raise DraftRiskGateError(
            "R3普通内容路径需要Human明确risk approval reason"
        )


def _validate_candidate_against_snapshot(
    candidate: ValidatedDraftCandidate,
    snapshot: DraftGenerationSnapshot,
) -> None:
    if candidate.draft_type is not snapshot.draft_type:
        raise DraftValidationError("模型返回的draft_type与请求不一致")
    if candidate.format_key is not snapshot.format_key:
        raise DraftValidationError(
            "模型不得改变Effective Editorial recommended format"
        )
    if len(candidate.body_text()) > draft_hard_max_chars(snapshot.draft_type):
        raise DraftValidationError("Draft正文超过该duration的工程hard max")

    seen: set[tuple[str, UUID]] = set()
    for section in candidate.sections:
        if section.section_kind == "factual":
            for citation in section.citations:
                state = snapshot.claim_states.get(citation.claim_id)
                if state is None:
                    raise UnsupportedDraftClaimError(
                        "Draft引用不存在或其他Event的Claim"
                    )
                marker = (section.section_key, citation.claim_id)
                if marker in seen:
                    raise DraftValidationError(
                        "同一section不能重复引用同一Claim"
                    )
                seen.add(marker)
                if citation.usage not in allowed_usages(state):
                    raise UnsafeDraftClaimUsageError(
                        f"{state.value} Claim不能以{citation.usage.value}语义进入Draft"
                    )
        else:
            for unknown_id in section.unknown_ids:
                if unknown_id not in snapshot.open_unknown_ids:
                    raise UnsupportedDraftUnknownError(
                        "Draft引用不存在、已解决或其他Event的Unknown"
                    )


def _validate_candidate_against_context(
    candidate: ValidatedDraftCandidate,
    context: EditorialContext,
) -> None:
    states = {item.id: item.verification_state for item in context.evidence.claims}
    unknowns = {
        item.id
        for item in context.evidence.unknowns
        if item.status.value == "open"
    }
    for section in candidate.sections:
        for citation in section.citations:
            state = states.get(citation.claim_id)
            if state is None:
                raise UnsupportedDraftClaimError(
                    "Apply时Claim已不存在于目标Event"
                )
            if citation.usage not in allowed_usages(state):
                raise StaleEditorialContextError(
                    "Apply时Claim verification已变化"
                )
        for unknown_id in section.unknown_ids:
            if unknown_id not in unknowns:
                raise StaleEditorialContextError(
                    "Apply时Unknown状态已变化"
                )


def _validate_human_references(
    references: Sequence[HumanDraftReference],
    context: EditorialContext,
) -> tuple[HumanDraftReference, ...]:
    states = {item.id: item.verification_state for item in context.evidence.claims}
    seen: set[tuple[str, UUID]] = set()
    result: list[HumanDraftReference] = []
    for item in references:
        section_key = normalize_text(item.section_key)
        state = states.get(item.claim_id)
        if state is None:
            raise UnsupportedDraftClaimError(
                "Human Draft引用不存在或其他Event Claim"
            )
        if not section_key:
            raise DraftValidationError("reference section_key不能为空")
        marker = (section_key, item.claim_id)
        if marker in seen:
            raise DraftValidationError(
                "同一section不能重复引用同一Claim"
            )
        seen.add(marker)
        if item.usage not in allowed_usages(state):
            raise UnsafeDraftClaimUsageError(
                f"{state.value} Claim不能以{item.usage.value}语义进入Human Draft"
            )
        result.append(
            HumanDraftReference(
                claim_id=item.claim_id,
                section_key=section_key,
                usage=item.usage,
            )
        )
    return tuple(result)


def _add_reference_rows(
    session: AsyncSession,
    draft_id: UUID,
    references: Sequence[HumanDraftReference],
) -> None:
    repo = DraftClaimReferenceRepository(session)
    for item in references:
        repo.add(
            DraftClaimReferenceRecord(
                draft_id=draft_id,
                claim_id=item.claim_id,
                section_key=item.section_key,
                usage=item.usage,
            )
        )


def _serialize_sections(
    candidate: ValidatedDraftCandidate,
) -> list[dict[str, Any]]:
    return [
        {
            "section_key": section.section_key,
            "section_kind": section.section_kind,
            "text": section.text,
            "citations": [
                {
                    "claim_id": str(item.claim_id),
                    "usage": item.usage.value,
                }
                for item in section.citations
            ],
            "unknown_ids": [str(item) for item in section.unknown_ids],
        }
        for section in candidate.sections
    ]


def _require_actor(actor: str) -> str:
    value = normalize_text(actor)
    if not value:
        raise DraftValidationError("Actor不能为空")
    return value


def _require_note(value: str, field: str) -> str:
    normalized = normalize_text(value)
    if not normalized:
        raise DraftValidationError(f"{field}不能为空")
    return normalized


def _optional(value: str | None) -> str | None:
    if value is None:
        return None
    return normalize_text(value) or None


def _candidate_list(value: str | None) -> list[str]:
    normalized = _optional(value)
    return [normalized] if normalized is not None else []


def _inherit_optional(value: str | None, previous: str | None) -> str | None:
    if value is None:
        return previous
    return _optional(value)


def _bounded_body(body: str, draft_type: DraftType) -> str:
    normalized = body.strip()
    if not normalized:
        raise DraftValidationError("Draft body不能为空")
    if len(normalized) > draft_hard_max_chars(draft_type):
        raise DraftValidationError(
            "Draft body超过该duration工程hard max"
        )
    return normalized


def _trend_markdown(trend: EventTrendSnapshotRecord | None) -> str:
    if trend is None:
        return "- unavailable: no Trend Snapshot bound to this Card"
    availability = json.dumps(
        trend.feature_availability,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return (
        f"- calculation_version: {trend.calculation_version}\n"
        f"- signal_velocity: {trend.signal_velocity}\n"
        f"- interaction_velocity: {trend.interaction_velocity}\n"
        f"- source_count: {trend.source_count}\n"
        f"- platform_count: {trend.platform_count}\n"
        f"- semantic_novelty: {trend.semantic_novelty}\n"
        f"- cn_gap: {trend.cn_gap}\n"
        f"- update_value: {trend.update_value}\n"
        f"- feature_availability: {availability}"
    )


def _claims_markdown(
    card: EventCardRecord,
    claims: dict[UUID, EvidenceClaimRecord],
) -> str:
    rows: list[str] = []
    groups = (
        ("confirmed", card.confirmed_claim_ids),
        ("investigating", card.investigating_claim_ids),
        ("single_source", card.single_source_claim_ids),
        ("disputed", card.disputed_claim_ids),
        ("false", card.false_claim_ids),
    )
    for state, ids in groups:
        for raw_id in ids:
            claim = claims.get(UUID(raw_id))
            if claim is not None:
                rows.append(
                    f"- [{state}] {claim.claim_text} (claim_id: {claim.id})"
                )
    return "\n".join(rows) if rows else "- none"


def _list_mapping(items: Sequence[dict[str, Any]], key: str) -> str:
    rows = [f"- {item.get(key, '')}" for item in items]
    return "\n".join(rows) if rows else "- none"


def _timeline_markdown(items: Sequence[dict[str, Any]]) -> str:
    rows = [
        (
            f"- {item.get('published_at') or item.get('collected_at')} | "
            f"{item.get('platform')} | {item.get('title') or '(untitled)'} | "
            f"{item.get('original_url')}"
        )
        for item in items
    ]
    return "\n".join(rows) if rows else "- none"


def _sources_markdown(items: Sequence[dict[str, Any]]) -> str:
    rows = [
        (
            f"- signal_id: {item.get('signal_id')} | {item.get('platform')} | "
            f"{item.get('original_url')}"
        )
        for item in items
    ]
    return "\n".join(rows) if rows else "- none"


def _materials_markdown(
    materials: Sequence[dict[str, Any]],
    warnings: Sequence[dict[str, Any]],
) -> str:
    rows = [
        (
            f"- {item.get('media_type')} | signal_id: {item.get('signal_id')} | "
            f"{item.get('source_url')} | {item.get('usage_note')}"
        )
        for item in materials
    ]
    rows.extend(
        f"- warning: {item.get('code')} | {item.get('message', '')}"
        for item in warnings
    )
    return "\n".join(rows) if rows else "- none"


def _draft_markdown(
    draft: EditorialDraftRecord | None,
    refs: Sequence[DraftClaimReferenceRecord],
) -> str:
    if draft is None:
        return "- no Draft selected"
    reference_lines = [
        (
            f"- {item.section_key}: claim_id={item.claim_id}, "
            f"usage={item.usage.value}"
        )
        for item in refs
    ]
    references = "\n".join(reference_lines) if reference_lines else "- none"
    return (
        f"### {draft.title or 'Untitled Draft'}\n\n"
        f"{draft.hook or ''}\n\n"
        f"{draft.body}\n\n"
        f"{draft.ending or ''}\n\n"
        f"Interaction: {draft.interaction_question or ''}\n\n"
        f"### Claim References\n{references}"
    )
