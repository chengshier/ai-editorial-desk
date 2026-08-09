from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from packages.ai_gateway.domain import AIMessage, GatewayStructuredResult, InvocationContext
from packages.ai_gateway.errors import AIGatewayError
from packages.ai_gateway.gateway import AIGateway
from packages.connector_management.exceptions import ConnectorManagementError, ResourceNotFoundError
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
)
from packages.database.session import get_async_sessionmaker
from packages.database.types import utc_now
from packages.editorial.domain import normalize_text, stable_hash
from packages.editorial.drafts_artifacts import assert_card_current
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
        messages: Sequence[AIMessage],
        schema: dict[str, Any],
        schema_name: str,
        max_output_tokens: int | None = None,
        temperature: float | None = None,
        context: InvocationContext | None = None,
        invocation_id: UUID | None = None,
    ) -> GatewayStructuredResult: ...


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
        _enforce_risk_gate(snapshot, apply=apply, approval_reason=risk_approval_reason)
        mode = DraftGenerationMode.APPLY if apply else DraftGenerationMode.PREVIEW
        if apply:
            existing = await self._existing_ai(snapshot)
            if existing is not None:
                return _reused(existing)

        run, created = await self._start_run(snapshot, actor=actor, mode=mode)
        if apply and not created:
            existing = await self._wait_for_existing_ai(snapshot)
            if existing is not None:
                return _reused(existing)
            if run.status is DraftGenerationStatus.RUNNING:
                raise DraftGenerationInProgressError("相同Draft输入已有Worker正在生成")
            raise DraftValidationError("相同Draft输入已有Run但没有可复用Draft")

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
            await self._finish_failed(run.id, invocation_id, exc.code.value, exc.message)
            raise

        try:
            candidate = validate_draft_candidate(result.data)
            _validate_candidate(candidate, snapshot)
        except ValueError as exc:
            await self._finish_failed(
                run.id,
                result.invocation_id,
                "DRAFT_OUTPUT_INVALID",
                str(exc),
            )
            raise DraftValidationError(str(exc)) from exc
        except ConnectorManagementError as exc:
            await self._finish_failed(run.id, result.invocation_id, exc.code, exc.message)
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
            draft, created = await self._apply(
                run_id=run.id,
                invocation_id=result.invocation_id,
                snapshot=snapshot,
                candidate=candidate,
                actor=actor,
            )
        except ConnectorManagementError as exc:
            await self._finish_failed(run.id, result.invocation_id, exc.code, exc.message)
            raise
        return DraftGenerationOutcome(
            run_id=run.id,
            ai_invocation_id=result.invocation_id,
            mode=mode,
            status=DraftGenerationStatus.SUCCEEDED,
            draft=draft,
            candidate=candidate,
            reused=not created,
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
                context = await load_editorial_context(session, event_id, for_update=True)
                card, pack = await _require_card_pack(
                    session,
                    event_id,
                    event_card_id,
                    editorial_pack_id,
                )
                assert_card_current(card, context)
                refs = _validate_human_refs(references, context)
                draft_id = uuid4()
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
                    input_hash=stable_hash(
                        {
                            "source_type": "human",
                            "event_id": str(event_id),
                            "card_id": str(card.id),
                            "pack_id": str(pack.id),
                            "context_hash": context.context_hash,
                            "draft_type": draft_type.value,
                            "body": body,
                            "references": _ref_hash_payload(refs),
                            "reason": reason,
                        }
                    ),
                    created_by_actor=actor,
                    change_note=reason,
                )
                EditorialDraftRepository(session).add_human(draft)
                await session.flush()
                _add_refs(session, draft.id, refs)
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
                context = await load_editorial_context(session, event_id, for_update=True)
                repo = EditorialDraftRepository(session)
                parent = await repo.get_for_update(parent_draft_id)
                if parent is None or parent.event_id != event_id:
                    raise ResourceNotFoundError("Parent Draft不存在")
                body = _bounded_body(body, parent.draft_type)
                latest = await repo.max_chain_version(parent.draft_chain_id)
                if latest != parent.draft_version:
                    raise DraftValidationError("只能基于当前chain最新Draft创建Revision")
                refs = _validate_human_refs(references, context)
                version = latest + 1
                draft = EditorialDraftRecord(
                    event_id=event_id,
                    event_card_id=parent.event_card_id,
                    editorial_pack_id=parent.editorial_pack_id,
                    draft_chain_id=parent.draft_chain_id,
                    draft_type=parent.draft_type,
                    format_key=parent.format_key,
                    duration_target_seconds=parent.duration_target_seconds,
                    language=parent.language,
                    draft_version=version,
                    parent_draft_id=parent.id,
                    source_type=DraftSourceType.HUMAN,
                    status=DraftStatus.EDITED,
                    title=_inherit(title, parent.title),
                    title_candidates=[],
                    hook=_inherit(hook, parent.hook),
                    hook_candidates=[],
                    cover_text_candidates=[],
                    sections=[],
                    body=body,
                    ending=_inherit(ending, parent.ending),
                    interaction_question=_inherit(
                        interaction_question,
                        parent.interaction_question,
                    ),
                    prompt_version=None,
                    schema_version=None,
                    ai_invocation_id=None,
                    generation_run_id=None,
                    input_hash=stable_hash(
                        {
                            "source_type": "human_revision",
                            "parent_draft_id": str(parent.id),
                            "draft_chain_id": str(parent.draft_chain_id),
                            "draft_version": version,
                            "context_hash": context.context_hash,
                            "body": body,
                            "references": _ref_hash_payload(refs),
                            "change_note": change_note,
                        }
                    ),
                    created_by_actor=actor,
                    change_note=change_note,
                )
                repo.add_human(draft)
                await session.flush()
                _add_refs(session, draft.id, refs)
                AuditLogRepository(session).add(
                    entity_type="editorial_draft",
                    entity_id=draft.id,
                    action="human_revision",
                    actor=actor,
                    before_data={
                        "parent_draft_id": str(parent.id),
                        "draft_version": parent.draft_version,
                    },
                    after_data={"draft_version": version, "change_note": change_note},
                )
                return draft

    async def list(self, event_id: UUID) -> tuple[EditorialDraftRecord, ...]:
        async with self.session_factory() as session:
            if await session.get(EventRecord, event_id) is None:
                raise ResourceNotFoundError("事件不存在")
            return tuple(await EditorialDraftRepository(session).list_for_event(event_id))

    async def detail(
        self, event_id: UUID, draft_id: UUID
    ) -> tuple[EditorialDraftRecord, tuple[DraftClaimReferenceRecord, ...]]:
        async with self.session_factory() as session:
            draft = await session.get(EditorialDraftRecord, draft_id)
            if draft is None or draft.event_id != event_id:
                raise ResourceNotFoundError("Draft不存在")
            refs = await DraftClaimReferenceRepository(session).list_for_draft(draft.id)
            return draft, tuple(refs)

    async def chain(self, event_id: UUID, draft_id: UUID) -> tuple[EditorialDraftRecord, ...]:
        async with self.session_factory() as session:
            draft = await session.get(EditorialDraftRecord, draft_id)
            if draft is None or draft.event_id != event_id:
                raise ResourceNotFoundError("Draft不存在")
            return tuple(await EditorialDraftRepository(session).list_chain(draft.draft_chain_id))

    async def _existing_ai(self, snapshot: DraftGenerationSnapshot) -> EditorialDraftRecord | None:
        async with self.session_factory() as session:
            return await EditorialDraftRepository(session).get_ai_by_input(
                event_card_id=snapshot.event_card_id,
                editorial_pack_id=snapshot.editorial_pack_id,
                draft_type=snapshot.draft_type,
                prompt_version=DRAFT_PROMPT_VERSION,
                schema_version=DRAFT_SCHEMA_VERSION,
                input_hash=snapshot.input_hash,
            )

    async def _wait_for_existing_ai(
        self, snapshot: DraftGenerationSnapshot
    ) -> EditorialDraftRecord | None:
        for _attempt in range(40):
            existing = await self._existing_ai(snapshot)
            if existing is not None:
                return existing
            await asyncio.sleep(0.05)
        return None

    async def _start_run(
        self,
        snapshot: DraftGenerationSnapshot,
        *,
        actor: str,
        mode: DraftGenerationMode,
    ) -> tuple[DraftGenerationRunRecord, bool]:
        async with self.session_factory() as session:
            async with session.begin():
                repo = DraftGenerationRunRepository(session)
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
                if mode is DraftGenerationMode.APPLY:
                    return await repo.claim_apply(values)
                run = DraftGenerationRunRecord(**values)
                repo.add(run)
                await session.flush()
                return run, True

    async def _apply(
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
                context = await load_editorial_context(session, snapshot.event_id, for_update=True)
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
                assert_card_current(card, context)
                _validate_candidate_against_context(candidate, context)
                run = await DraftGenerationRunRepository(session).get_for_update(run_id)
                if run is None:
                    raise RuntimeError("Draft Generation Run不存在")
                draft_id = uuid4()
                draft, created = await EditorialDraftRepository(session).insert_ai_if_absent(
                    {
                        "id": draft_id,
                        "event_id": snapshot.event_id,
                        "event_card_id": snapshot.event_card_id,
                        "editorial_pack_id": snapshot.editorial_pack_id,
                        "draft_chain_id": draft_id,
                        "draft_type": snapshot.draft_type,
                        "format_key": snapshot.format_key,
                        "duration_target_seconds": snapshot.duration_target_seconds,
                        "language": context.event.primary_language or "zh-CN",
                        "draft_version": 1,
                        "parent_draft_id": None,
                        "source_type": DraftSourceType.AI,
                        "status": DraftStatus.GENERATED,
                        "title": candidate.title_candidates[0],
                        "title_candidates": list(candidate.title_candidates),
                        "hook": candidate.hook_candidates[0],
                        "hook_candidates": list(candidate.hook_candidates),
                        "cover_text_candidates": list(candidate.cover_text_candidates),
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
                    after_data={"event_id": str(event_id), "risk_level": "R3", "reason": reason},
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
    snapshot: DraftGenerationSnapshot, *, apply: bool, approval_reason: str | None
) -> None:
    if not apply:
        return
    if snapshot.risk_level is EditorialRiskLevel.R4:
        if snapshot.format_key is not EditorialRecommendedFormat.FACT_CHECK:
            raise DraftRiskGateError("R4只允许fact_check AI Draft Apply；Event不会因此被删除")
        return
    safe_r3 = {EditorialRecommendedFormat.FACT_CHECK, EditorialRecommendedFormat.QUICK_EXPLAINER}
    if (
        snapshot.risk_level is EditorialRiskLevel.R3
        and snapshot.format_key not in safe_r3
        and not normalize_text(approval_reason or "")
    ):
        raise DraftRiskGateError("R3普通内容路径需要Human明确risk approval reason")


def _validate_candidate(
    candidate: ValidatedDraftCandidate,
    snapshot: DraftGenerationSnapshot,
) -> None:
    if candidate.draft_type is not snapshot.draft_type:
        raise DraftValidationError("模型返回的draft_type与请求不一致")
    if candidate.format_key is not snapshot.format_key:
        raise DraftValidationError("模型不得改变Effective Editorial recommended format")
    if len(candidate.body_text()) > draft_hard_max_chars(snapshot.draft_type):
        raise DraftValidationError("Draft正文超过该duration工程hard max")
    seen: set[tuple[str, UUID]] = set()
    for section in candidate.sections:
        if section.section_kind == "factual":
            for citation in section.citations:
                state = snapshot.claim_states.get(citation.claim_id)
                if state is None:
                    raise UnsupportedDraftClaimError("Draft引用不存在或其他Event的Claim")
                marker = (section.section_key, citation.claim_id)
                if marker in seen:
                    raise DraftValidationError("同一section不能重复引用同一Claim")
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
    candidate: ValidatedDraftCandidate, context: EditorialContext
) -> None:
    states = {claim.id: claim.verification_state for claim in context.evidence.claims}
    unknowns = {item.id for item in context.evidence.unknowns if item.status.value == "open"}
    for section in candidate.sections:
        for citation in section.citations:
            state = states.get(citation.claim_id)
            if state is None:
                raise UnsupportedDraftClaimError("Apply时Claim已不存在于目标Event")
            if citation.usage not in allowed_usages(state):
                raise StaleEditorialContextError("Apply时Claim verification已变化")
        for unknown_id in section.unknown_ids:
            if unknown_id not in unknowns:
                raise StaleEditorialContextError("Apply时Unknown状态已变化")


def _validate_human_refs(
    references: Sequence[HumanDraftReference], context: EditorialContext
) -> tuple[HumanDraftReference, ...]:
    states = {claim.id: claim.verification_state for claim in context.evidence.claims}
    seen: set[tuple[str, UUID]] = set()
    result: list[HumanDraftReference] = []
    for ref in references:
        section = normalize_text(ref.section_key)
        state = states.get(ref.claim_id)
        if state is None:
            raise UnsupportedDraftClaimError("Human Draft引用不存在或其他Event Claim")
        if not section:
            raise DraftValidationError("reference section_key不能为空")
        marker = (section, ref.claim_id)
        if marker in seen:
            raise DraftValidationError("同一section不能重复引用同一Claim")
        seen.add(marker)
        if ref.usage not in allowed_usages(state):
            raise UnsafeDraftClaimUsageError(
                f"{state.value} Claim不能以{ref.usage.value}语义进入Human Draft"
            )
        result.append(HumanDraftReference(ref.claim_id, section, ref.usage))
    return tuple(result)


def _add_refs(session: AsyncSession, draft_id: UUID, refs: Sequence[HumanDraftReference]) -> None:
    repo = DraftClaimReferenceRepository(session)
    for ref in refs:
        repo.add(
            DraftClaimReferenceRecord(
                draft_id=draft_id,
                claim_id=ref.claim_id,
                section_key=ref.section_key,
                usage=ref.usage,
            )
        )


def _serialize_sections(candidate: ValidatedDraftCandidate) -> list[dict[str, Any]]:
    return [
        {
            "section_key": section.section_key,
            "section_kind": section.section_kind,
            "text": section.text,
            "citations": [
                {"claim_id": str(ref.claim_id), "usage": ref.usage.value}
                for ref in section.citations
            ],
            "unknown_ids": [str(item) for item in section.unknown_ids],
        }
        for section in candidate.sections
    ]


def _ref_hash_payload(refs: Sequence[HumanDraftReference]) -> list[tuple[str, str, str]]:
    return [(str(ref.claim_id), ref.section_key, ref.usage.value) for ref in refs]


def _require_actor(actor: str) -> str:
    actor = normalize_text(actor)
    if not actor:
        raise DraftValidationError("Actor不能为空")
    return actor


def _require_note(value: str, field: str) -> str:
    value = normalize_text(value)
    if not value:
        raise DraftValidationError(f"{field}不能为空")
    return value


def _optional(value: str | None) -> str | None:
    return normalize_text(value) or None if value is not None else None


def _candidate_list(value: str | None) -> list[str]:
    value = _optional(value)
    return [value] if value is not None else []


def _inherit(value: str | None, previous: str | None) -> str | None:
    return previous if value is None else _optional(value)


def _bounded_body(body: str, draft_type: DraftType) -> str:
    body = body.strip()
    if not body:
        raise DraftValidationError("Draft body不能为空")
    if len(body) > draft_hard_max_chars(draft_type):
        raise DraftValidationError("Draft body超过该duration工程hard max")
    return body


def _reused(draft: EditorialDraftRecord) -> DraftGenerationOutcome:
    return DraftGenerationOutcome(
        run_id=draft.generation_run_id,
        ai_invocation_id=draft.ai_invocation_id,
        mode=DraftGenerationMode.APPLY,
        status=DraftGenerationStatus.SUCCEEDED,
        draft=draft,
        candidate=None,
        reused=True,
    )