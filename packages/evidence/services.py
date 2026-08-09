from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from packages.ai_gateway.domain import (
    AIMessage,
    GatewayStructuredResult,
    InvocationContext,
)
from packages.ai_gateway.errors import AIGatewayError
from packages.ai_gateway.gateway import AIGateway
from packages.connector_management.exceptions import ResourceNotFoundError
from packages.connector_management.repositories import AuditLogRepository
from packages.database.models import (
    AIInvocationRecord,
    EventRecord,
    EventSignalRecord,
    EventUnknownRecord,
    EventUnknownSourceType,
    EventUnknownStatus,
    EvidenceClaimRecord,
    EvidenceClaimType,
    EvidenceCreatedByType,
    EvidenceExtractionRunMode,
    EvidenceExtractionRunRecord,
    EvidenceExtractionRunStatus,
    EvidenceSourceRole,
    EvidenceVerificationState,
    RawSignalRecord,
)
from packages.database.session import get_async_sessionmaker
from packages.database.types import utc_now
from packages.evidence.domain import (
    DEFAULT_MAX_CHARS_PER_SIGNAL,
    DEFAULT_MAX_SIGNALS,
    DEFAULT_MAX_TOTAL_CHARS,
    EVIDENCE_EXTRACTION_VERSION,
    EVIDENCE_PROMPT_VERSION,
    EVIDENCE_SCHEMA_NAME,
    EVIDENCE_SCHEMA_V1,
    EVIDENCE_SCHEMA_VERSION,
    CandidateClaim,
    ExtractionValidationResult,
    claim_fingerprint,
    normalize_evidence_text,
    unknown_fingerprint,
    validate_extraction_data,
)
from packages.evidence.errors import (
    EventMergedError,
    EvidenceSourceConflictError,
    EvidenceValidationError,
)
from packages.evidence.input_builder import EvidenceInputBuilder
from packages.evidence.repositories import (
    EventUnknownRepository,
    EvidenceClaimRepository,
    EvidenceClaimSourceRepository,
    EvidenceExtractionRunRepository,
)


class StructuredGateway(Protocol):
    async def generate_structured(
        self,
        *,
        task_key: str,
        messages: tuple[AIMessage, ...],
        schema: dict[str, object],
        schema_name: str,
        max_output_tokens: int | None = None,
        temperature: float | None = None,
        context: InvocationContext | None = None,
        invocation_id: UUID | None = None,
    ) -> GatewayStructuredResult: ...


@dataclass(frozen=True, slots=True)
class EvidenceSourceView:
    signal_id: UUID
    role: EvidenceSourceRole
    title: str | None
    platform: str
    author_name: str | None
    published_at: object | None
    collected_at: object
    original_url: str
    canonical_url: str


@dataclass(frozen=True, slots=True)
class ClaimEvidenceView:
    claim: EvidenceClaimRecord
    sources: tuple[EvidenceSourceView, ...]


@dataclass(frozen=True, slots=True)
class EventEvidenceView:
    event_id: UUID
    claims: tuple[ClaimEvidenceView, ...]
    unknowns: tuple[EventUnknownRecord, ...]


@dataclass(frozen=True, slots=True)
class ExtractionOutcome:
    run_id: UUID
    ai_invocation_id: UUID | None
    mode: EvidenceExtractionRunMode
    status: EvidenceExtractionRunStatus
    claim_count: int
    unknown_count: int
    invalid_item_count: int
    invalid_codes: tuple[str, ...]
    signal_count: int
    character_count: int
    truncated: bool
    truncated_signal_ids: tuple[UUID, ...]


class EventEvidenceService:
    """Human-controlled Claim, source, Unknown and verification workflow."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self.session_factory = session_factory or get_async_sessionmaker()

    async def get_evidence(self, event_id: UUID) -> EventEvidenceView:
        async with self.session_factory() as session:
            event = await session.get(EventRecord, event_id)
            if event is None:
                raise ResourceNotFoundError("事件不存在")
            claims = await EvidenceClaimRepository(session).list_for_event(event_id)
            unknowns = await EventUnknownRepository(session).list_for_event(event_id)
            source_repo = EvidenceClaimSourceRepository(session)
            links_by_claim = {
                claim.id: tuple(await source_repo.list_for_claim(claim.id)) for claim in claims
            }
            signal_ids = {
                link.signal_id for links in links_by_claim.values() for link in links
            }
            signals: dict[UUID, RawSignalRecord] = {}
            if signal_ids:
                statement = select(RawSignalRecord).where(RawSignalRecord.id.in_(signal_ids))
                signals = {
                    item.id: item for item in (await session.scalars(statement)).all()
                }

            claim_views: list[ClaimEvidenceView] = []
            for claim in claims:
                source_views: list[EvidenceSourceView] = []
                for link in links_by_claim[claim.id]:
                    signal = signals.get(link.signal_id)
                    if signal is None:
                        raise RuntimeError("Evidence source FK 存在但 RawSignal 未找到")
                    source_views.append(
                        EvidenceSourceView(
                            signal_id=signal.id,
                            role=link.role,
                            title=signal.title,
                            platform=signal.platform,
                            author_name=signal.author_name,
                            published_at=signal.published_at,
                            collected_at=signal.collected_at,
                            original_url=signal.original_url,
                            canonical_url=signal.canonical_url,
                        )
                    )
                source_views.sort(
                    key=lambda item: (
                        item.published_at or item.collected_at,
                        str(item.signal_id),
                    )
                )
                claim_views.append(
                    ClaimEvidenceView(claim=claim, sources=tuple(source_views))
                )
            return EventEvidenceView(
                event_id=event_id,
                claims=tuple(claim_views),
                unknowns=tuple(unknowns),
            )

    async def create_human_claim(
        self,
        *,
        event_id: UUID,
        actor: str,
        claim_text: str,
        claim_type: EvidenceClaimType,
        sources: Sequence[tuple[UUID, EvidenceSourceRole]],
        editor_note: str | None = None,
    ) -> EvidenceClaimRecord:
        normalized = normalize_evidence_text(claim_text)
        if not normalized:
            raise EvidenceValidationError("Claim text 不能为空")
        source_map = _normalize_source_pairs(sources)
        if not source_map:
            raise EvidenceValidationError("人工 Claim 至少需要一个 Evidence source")

        async with self.session_factory() as session:
            async with session.begin():
                await _require_active_event(session, event_id, for_update=True)
                await _require_event_membership(session, event_id, set(source_map))
                claim_repo = EvidenceClaimRepository(session)
                claim, created = await claim_repo.insert_if_absent(
                    event_id=event_id,
                    claim_text=normalized,
                    claim_type=claim_type,
                    verification_state=_initial_state(source_map),
                    extraction_confidence=None,
                    claim_fingerprint=claim_fingerprint(normalized, claim_type),
                    extraction_version=EVIDENCE_EXTRACTION_VERSION,
                    extraction_run_id=None,
                    ai_invocation_id=None,
                    created_by_type=EvidenceCreatedByType.HUMAN,
                    created_by_actor=actor,
                    editor_note=_normalized_optional(editor_note),
                )
                source_repo = EvidenceClaimSourceRepository(session)
                for signal_id, role in source_map.items():
                    existing, link_created = await source_repo.attach_if_absent(
                        claim_id=claim.id,
                        signal_id=signal_id,
                        role=role,
                    )
                    if not link_created and existing.role is not role:
                        raise EvidenceSourceConflictError(
                            "同一 Signal 不能同时作为 supporting 与 contradicting"
                        )
                AuditLogRepository(session).add(
                    entity_type="evidence_claim",
                    entity_id=claim.id,
                    action="human_create" if created else "human_attach_sources",
                    actor=actor,
                    before_data={},
                    after_data={
                        "event_id": str(event_id),
                        "claim_type": claim.claim_type.value,
                        "verification_state": claim.verification_state.value,
                        "source_ids": [str(item) for item in sorted(source_map, key=str)],
                    },
                )
                return claim

    async def attach_source(
        self,
        *,
        event_id: UUID,
        claim_id: UUID,
        signal_id: UUID,
        role: EvidenceSourceRole,
        actor: str,
    ) -> tuple[EvidenceClaimRecord, bool]:
        async with self.session_factory() as session:
            async with session.begin():
                await _require_active_event(session, event_id, for_update=True)
                claim = await _require_claim(session, event_id, claim_id, for_update=True)
                await _require_event_membership(session, event_id, {signal_id})
                source_repo = EvidenceClaimSourceRepository(session)
                link, created = await source_repo.attach_if_absent(
                    claim_id=claim.id,
                    signal_id=signal_id,
                    role=role,
                )
                if not created and link.role is not role:
                    raise EvidenceSourceConflictError(
                        "同一 Signal 已以另一 Evidence role 关联该 Claim"
                    )
                if created:
                    AuditLogRepository(session).add(
                        entity_type="evidence_claim",
                        entity_id=claim.id,
                        action="attach_source",
                        actor=actor,
                        before_data={},
                        after_data={"signal_id": str(signal_id), "role": role.value},
                    )
                return claim, created

    async def remove_source(
        self,
        *,
        event_id: UUID,
        claim_id: UUID,
        signal_id: UUID,
        actor: str,
    ) -> bool:
        async with self.session_factory() as session:
            async with session.begin():
                await _require_active_event(session, event_id, for_update=True)
                claim = await _require_claim(session, event_id, claim_id, for_update=True)
                source_repo = EvidenceClaimSourceRepository(session)
                source = await source_repo.get(claim.id, signal_id)
                if source is None:
                    return False
                links = await source_repo.list_for_claim(claim.id)
                support_count = sum(
                    item.role is EvidenceSourceRole.SUPPORTING for item in links
                )
                contradiction_count = sum(
                    item.role is EvidenceSourceRole.CONTRADICTING for item in links
                )
                if (
                    claim.verification_state is EvidenceVerificationState.CONFIRMED
                    and source.role is EvidenceSourceRole.SUPPORTING
                    and support_count <= 1
                ):
                    raise EvidenceValidationError(
                        "confirmed Claim 不能删除最后一个 supporting source"
                    )
                if (
                    claim.verification_state is EvidenceVerificationState.FALSE
                    and source.role is EvidenceSourceRole.CONTRADICTING
                    and contradiction_count <= 1
                ):
                    raise EvidenceValidationError(
                        "false Claim 不能删除最后一个 contradicting source"
                    )
                await source_repo.delete(source)
                AuditLogRepository(session).add(
                    entity_type="evidence_claim",
                    entity_id=claim.id,
                    action="remove_source",
                    actor=actor,
                    before_data={"signal_id": str(signal_id), "role": source.role.value},
                    after_data={},
                )
                return True

    async def verify_claim(
        self,
        *,
        event_id: UUID,
        claim_id: UUID,
        verification_state: EvidenceVerificationState,
        reason: str,
        actor: str,
    ) -> EvidenceClaimRecord:
        normalized_reason = normalize_evidence_text(reason)
        if not normalized_reason:
            raise EvidenceValidationError("Verification reason 不能为空")
        async with self.session_factory() as session:
            async with session.begin():
                await _require_active_event(session, event_id, for_update=True)
                claim = await _require_claim(session, event_id, claim_id, for_update=True)
                links = await EvidenceClaimSourceRepository(session).list_for_claim(claim.id)
                support_count = sum(
                    item.role is EvidenceSourceRole.SUPPORTING for item in links
                )
                contradiction_count = sum(
                    item.role is EvidenceSourceRole.CONTRADICTING for item in links
                )
                if (
                    verification_state is EvidenceVerificationState.CONFIRMED
                    and support_count == 0
                ):
                    raise EvidenceValidationError(
                        "confirmed Claim 至少需要一个 supporting source"
                    )
                if (
                    verification_state is EvidenceVerificationState.FALSE
                    and contradiction_count == 0
                ):
                    raise EvidenceValidationError(
                        "false Claim 至少需要一个 contradicting source"
                    )
                before = claim.verification_state
                claim.verification_state = verification_state
                claim.editor_note = normalized_reason
                await session.flush()
                AuditLogRepository(session).add(
                    entity_type="evidence_claim",
                    entity_id=claim.id,
                    action="verify",
                    actor=actor,
                    before_data={"verification_state": before.value},
                    after_data={
                        "verification_state": verification_state.value,
                        "reason": normalized_reason,
                        "supporting_count": support_count,
                        "contradicting_count": contradiction_count,
                    },
                )
                return claim

    async def update_claim_note(
        self,
        *,
        event_id: UUID,
        claim_id: UUID,
        editor_note: str,
        actor: str,
    ) -> EvidenceClaimRecord:
        note = normalize_evidence_text(editor_note)
        if not note:
            raise EvidenceValidationError("editor_note 不能为空")
        async with self.session_factory() as session:
            async with session.begin():
                await _require_active_event(session, event_id, for_update=True)
                claim = await _require_claim(session, event_id, claim_id, for_update=True)
                before = claim.editor_note
                claim.editor_note = note
                await session.flush()
                AuditLogRepository(session).add(
                    entity_type="evidence_claim",
                    entity_id=claim.id,
                    action="update_note",
                    actor=actor,
                    before_data={"editor_note": before},
                    after_data={"editor_note": note},
                )
                return claim

    async def create_unknown(
        self,
        *,
        event_id: UUID,
        unknown_text: str,
        actor: str,
    ) -> EventUnknownRecord:
        normalized = normalize_evidence_text(unknown_text)
        if not normalized:
            raise EvidenceValidationError("Unknown text 不能为空")
        async with self.session_factory() as session:
            async with session.begin():
                await _require_active_event(session, event_id, for_update=True)
                unknown, created = await EventUnknownRepository(session).insert_if_absent(
                    event_id=event_id,
                    unknown_text=normalized,
                    unknown_fingerprint=unknown_fingerprint(normalized),
                    status=EventUnknownStatus.OPEN,
                    source_type=EventUnknownSourceType.HUMAN,
                    extraction_run_id=None,
                    ai_invocation_id=None,
                    created_by_actor=actor,
                )
                if created:
                    AuditLogRepository(session).add(
                        entity_type="event_unknown",
                        entity_id=unknown.id,
                        action="human_create",
                        actor=actor,
                        before_data={},
                        after_data={"event_id": str(event_id), "status": unknown.status.value},
                    )
                return unknown

    async def update_unknown(
        self,
        *,
        event_id: UUID,
        unknown_id: UUID,
        status: EventUnknownStatus,
        actor: str,
        resolution_note: str | None = None,
        resolved_by_claim_id: UUID | None = None,
    ) -> EventUnknownRecord:
        async with self.session_factory() as session:
            async with session.begin():
                await _require_active_event(session, event_id, for_update=True)
                unknown = await EventUnknownRepository(session).get_for_update(unknown_id)
                if unknown is None or unknown.event_id != event_id:
                    raise ResourceNotFoundError("Unknown 不存在")
                if resolved_by_claim_id is not None:
                    await _require_claim(
                        session,
                        event_id,
                        resolved_by_claim_id,
                        for_update=False,
                    )
                note = _normalized_optional(resolution_note)
                if status is not EventUnknownStatus.OPEN and not note:
                    raise EvidenceValidationError(
                        "resolved/dismissed Unknown 需要 resolution_note"
                    )
                before = {
                    "status": unknown.status.value,
                    "resolved_by_claim_id": (
                        str(unknown.resolved_by_claim_id)
                        if unknown.resolved_by_claim_id
                        else None
                    ),
                }
                unknown.status = status
                unknown.resolution_note = note
                unknown.resolved_by_claim_id = resolved_by_claim_id
                await session.flush()
                AuditLogRepository(session).add(
                    entity_type="event_unknown",
                    entity_id=unknown.id,
                    action="update",
                    actor=actor,
                    before_data=before,
                    after_data={
                        "status": status.value,
                        "resolved_by_claim_id": (
                            str(resolved_by_claim_id) if resolved_by_claim_id else None
                        ),
                        "resolution_note": note,
                    },
                )
                return unknown


class EvidenceExtractionService:
    """AI candidate extraction through M4-A Gateway with a separate business apply phase."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        gateway: StructuredGateway | None = None,
    ) -> None:
        self.session_factory = session_factory or get_async_sessionmaker()
        self.gateway = gateway or AIGateway(session_factory=self.session_factory)
        self.input_builder = EvidenceInputBuilder(self.session_factory)

    async def extract(
        self,
        *,
        event_id: UUID,
        actor: str,
        apply: bool,
        signal_ids: Sequence[UUID] | None = None,
        max_signals: int = DEFAULT_MAX_SIGNALS,
        max_chars_per_signal: int = DEFAULT_MAX_CHARS_PER_SIGNAL,
        max_total_chars: int = DEFAULT_MAX_TOTAL_CHARS,
    ) -> ExtractionOutcome:
        snapshot = await self.input_builder.build(
            event_id=event_id,
            signal_ids=signal_ids,
            max_signals=max_signals,
            max_chars_per_signal=max_chars_per_signal,
            max_total_chars=max_total_chars,
        )
        if not snapshot.signals:
            raise EvidenceValidationError("Event 没有可用于 Evidence extraction 的 Signal")

        mode = (
            EvidenceExtractionRunMode.APPLY
            if apply
            else EvidenceExtractionRunMode.PREVIEW
        )
        run = EvidenceExtractionRunRecord(
            event_id=event_id,
            ai_invocation_id=None,
            extraction_version=EVIDENCE_EXTRACTION_VERSION,
            prompt_version=EVIDENCE_PROMPT_VERSION,
            schema_version=EVIDENCE_SCHEMA_VERSION,
            mode=mode,
            status=EvidenceExtractionRunStatus.RUNNING,
            requested_signal_count=len(snapshot.signals),
            claim_count=0,
            unknown_count=0,
            invalid_item_count=0,
            character_count=snapshot.character_count,
            input_hash=snapshot.input_hash,
            truncated=snapshot.truncated,
            requested_by=actor,
            error_code=None,
            error_summary=None,
        )
        async with self.session_factory() as session:
            async with session.begin():
                EvidenceExtractionRunRepository(session).add(run)
                await session.flush()
                run_id = run.id

        invocation_id = uuid4()
        try:
            gateway_result = await self.gateway.generate_structured(
                task_key="evidence_extraction",
                messages=snapshot.messages(),
                schema=EVIDENCE_SCHEMA_V1,
                schema_name=EVIDENCE_SCHEMA_NAME,
                max_output_tokens=2048,
                temperature=0.0,
                context=InvocationContext(
                    prompt_version=EVIDENCE_PROMPT_VERSION,
                    schema_version=EVIDENCE_SCHEMA_VERSION,
                    subject_type="event",
                    subject_id=str(event_id),
                    metadata={
                        "evidence_extraction_run_id": str(run_id),
                        "signal_count": len(snapshot.signals),
                        "character_count": snapshot.character_count,
                        "truncated": snapshot.truncated,
                        "truncated_signal_ids": [
                            str(item) for item in snapshot.truncated_signal_ids
                        ],
                    },
                ),
                invocation_id=invocation_id,
            )
        except AIGatewayError as exc:
            await self._finish_failed_run(
                run_id=run_id,
                invocation_id=invocation_id,
                error_code=exc.code.value,
                error_summary=exc.message,
            )
            raise

        validation = validate_extraction_data(
            gateway_result.data,
            allowed_signal_ids={item.signal_id for item in snapshot.signals},
        )
        if not apply:
            status = (
                EvidenceExtractionRunStatus.PARTIAL
                if validation.invalid_item_count
                else EvidenceExtractionRunStatus.SUCCEEDED
            )
            await self._finish_preview_run(
                run_id=run_id,
                invocation_id=gateway_result.invocation_id,
                validation=validation,
                status=status,
            )
            return _outcome(
                run_id=run_id,
                invocation_id=gateway_result.invocation_id,
                mode=mode,
                status=status,
                validation=validation,
                signal_count=len(snapshot.signals),
                character_count=snapshot.character_count,
                truncated_signal_ids=snapshot.truncated_signal_ids,
            )

        try:
            status, validation = await self._apply(
                run_id=run_id,
                event_id=event_id,
                actor=actor,
                invocation_id=gateway_result.invocation_id,
                validation=validation,
            )
        except EventMergedError as exc:
            await self._finish_failed_run(
                run_id=run_id,
                invocation_id=gateway_result.invocation_id,
                error_code=exc.code,
                error_summary=exc.message,
            )
            raise
        return _outcome(
            run_id=run_id,
            invocation_id=gateway_result.invocation_id,
            mode=mode,
            status=status,
            validation=validation,
            signal_count=len(snapshot.signals),
            character_count=snapshot.character_count,
            truncated_signal_ids=snapshot.truncated_signal_ids,
        )

    async def _apply(
        self,
        *,
        run_id: UUID,
        event_id: UUID,
        actor: str,
        invocation_id: UUID,
        validation: ExtractionValidationResult,
    ) -> tuple[EvidenceExtractionRunStatus, ExtractionValidationResult]:
        invalid_codes = list(validation.invalid_codes)
        valid_claims: list[CandidateClaim] = []
        valid_unknowns = list(validation.unknowns)
        async with self.session_factory() as session:
            async with session.begin():
                await _require_active_event(session, event_id, for_update=True)
                current_membership = set(
                    (
                        await session.scalars(
                            select(EventSignalRecord.signal_id).where(
                                EventSignalRecord.event_id == event_id
                            )
                        )
                    ).all()
                )
                claim_repo = EvidenceClaimRepository(session)
                source_repo = EvidenceClaimSourceRepository(session)
                unknown_repo = EventUnknownRepository(session)

                for candidate in validation.claims:
                    evidence_ids = set(candidate.supporting_signal_ids) | set(
                        candidate.contradicting_signal_ids
                    )
                    if not evidence_ids.issubset(current_membership):
                        invalid_codes.append("SIGNAL_NOT_IN_EVENT_AT_APPLY")
                        continue
                    source_map = {
                        item: EvidenceSourceRole.SUPPORTING
                        for item in candidate.supporting_signal_ids
                    }
                    source_map.update(
                        {
                            item: EvidenceSourceRole.CONTRADICTING
                            for item in candidate.contradicting_signal_ids
                        }
                    )
                    claim, _created = await claim_repo.insert_if_absent(
                        event_id=event_id,
                        claim_text=candidate.text,
                        claim_type=candidate.claim_type,
                        verification_state=_initial_state(source_map),
                        extraction_confidence=candidate.confidence,
                        claim_fingerprint=candidate.fingerprint,
                        extraction_version=EVIDENCE_EXTRACTION_VERSION,
                        extraction_run_id=run_id,
                        ai_invocation_id=invocation_id,
                        created_by_type=EvidenceCreatedByType.AI,
                        created_by_actor=None,
                        editor_note=None,
                    )
                    role_conflict = False
                    for signal_id, role in source_map.items():
                        existing, created = await source_repo.attach_if_absent(
                            claim_id=claim.id,
                            signal_id=signal_id,
                            role=role,
                        )
                        if not created and existing.role is not role:
                            invalid_codes.append("SOURCE_ROLE_CONFLICT_AT_APPLY")
                            role_conflict = True
                    if not role_conflict:
                        valid_claims.append(candidate)

                for candidate in valid_unknowns:
                    await unknown_repo.insert_if_absent(
                        event_id=event_id,
                        unknown_text=candidate.text,
                        unknown_fingerprint=candidate.fingerprint,
                        status=EventUnknownStatus.OPEN,
                        source_type=EventUnknownSourceType.AI,
                        extraction_run_id=run_id,
                        ai_invocation_id=invocation_id,
                        created_by_actor=None,
                    )

                final_validation = ExtractionValidationResult(
                    claims=tuple(valid_claims),
                    unknowns=tuple(valid_unknowns),
                    invalid_codes=tuple(invalid_codes),
                )
                status = (
                    EvidenceExtractionRunStatus.PARTIAL
                    if invalid_codes
                    else EvidenceExtractionRunStatus.SUCCEEDED
                )
                run = await EvidenceExtractionRunRepository(session).get_for_update(run_id)
                if run is None:
                    raise RuntimeError("EvidenceExtractionRun 不存在")
                run.ai_invocation_id = invocation_id
                run.status = status
                run.claim_count = len(valid_claims)
                run.unknown_count = len(valid_unknowns)
                run.invalid_item_count = len(invalid_codes)
                run.finished_at = utc_now()
                await session.flush()
                AuditLogRepository(session).add(
                    entity_type="evidence_extraction_run",
                    entity_id=run.id,
                    action="apply",
                    actor=actor,
                    before_data={},
                    after_data={
                        "event_id": str(event_id),
                        "ai_invocation_id": str(invocation_id),
                        "claim_count": run.claim_count,
                        "unknown_count": run.unknown_count,
                        "invalid_item_count": run.invalid_item_count,
                        "invalid_codes": invalid_codes,
                        "status": status.value,
                    },
                )
                return status, final_validation

    async def _finish_preview_run(
        self,
        *,
        run_id: UUID,
        invocation_id: UUID,
        validation: ExtractionValidationResult,
        status: EvidenceExtractionRunStatus,
    ) -> None:
        async with self.session_factory() as session:
            async with session.begin():
                run = await EvidenceExtractionRunRepository(session).get_for_update(run_id)
                if run is None:
                    raise RuntimeError("EvidenceExtractionRun 不存在")
                run.ai_invocation_id = invocation_id
                run.status = status
                run.claim_count = len(validation.claims)
                run.unknown_count = len(validation.unknowns)
                run.invalid_item_count = validation.invalid_item_count
                run.finished_at = utc_now()

    async def _finish_failed_run(
        self,
        *,
        run_id: UUID,
        invocation_id: UUID,
        error_code: str,
        error_summary: str,
    ) -> None:
        async with self.session_factory() as session:
            async with session.begin():
                run = await EvidenceExtractionRunRepository(session).get_for_update(run_id)
                if run is None:
                    return
                invocation = await session.get(AIInvocationRecord, invocation_id)
                run.ai_invocation_id = invocation.id if invocation is not None else None
                run.status = EvidenceExtractionRunStatus.FAILED
                run.error_code = error_code[:100]
                run.error_summary = error_summary[:1000]
                run.finished_at = utc_now()


def _outcome(
    *,
    run_id: UUID,
    invocation_id: UUID | None,
    mode: EvidenceExtractionRunMode,
    status: EvidenceExtractionRunStatus,
    validation: ExtractionValidationResult,
    signal_count: int,
    character_count: int,
    truncated_signal_ids: tuple[UUID, ...],
) -> ExtractionOutcome:
    return ExtractionOutcome(
        run_id=run_id,
        ai_invocation_id=invocation_id,
        mode=mode,
        status=status,
        claim_count=len(validation.claims),
        unknown_count=len(validation.unknowns),
        invalid_item_count=validation.invalid_item_count,
        invalid_codes=validation.invalid_codes,
        signal_count=signal_count,
        character_count=character_count,
        truncated=bool(truncated_signal_ids),
        truncated_signal_ids=truncated_signal_ids,
    )


async def _require_active_event(
    session: AsyncSession,
    event_id: UUID,
    *,
    for_update: bool,
) -> EventRecord:
    statement = select(EventRecord).where(EventRecord.id == event_id)
    if for_update:
        statement = statement.with_for_update()
    event = (await session.execute(statement)).scalar_one_or_none()
    if event is None:
        raise ResourceNotFoundError("事件不存在")
    if event.merged_into_event_id is not None:
        raise EventMergedError(event.merged_into_event_id)
    return event


async def _require_claim(
    session: AsyncSession,
    event_id: UUID,
    claim_id: UUID,
    *,
    for_update: bool,
) -> EvidenceClaimRecord:
    statement = select(EvidenceClaimRecord).where(
        EvidenceClaimRecord.id == claim_id,
        EvidenceClaimRecord.event_id == event_id,
    )
    if for_update:
        statement = statement.with_for_update()
    claim = (await session.execute(statement)).scalar_one_or_none()
    if claim is None:
        raise ResourceNotFoundError("Evidence Claim 不存在")
    return claim


async def _require_event_membership(
    session: AsyncSession,
    event_id: UUID,
    signal_ids: set[UUID],
) -> None:
    if not signal_ids:
        raise EvidenceValidationError("Evidence source 不能为空")
    members = set(
        (
            await session.scalars(
                select(EventSignalRecord.signal_id).where(
                    EventSignalRecord.event_id == event_id,
                    EventSignalRecord.signal_id.in_(signal_ids),
                )
            )
        ).all()
    )
    missing = sorted(signal_ids - members, key=str)
    if missing:
        raise EvidenceValidationError(
            "Evidence source 必须属于目标 Event",
            details={"signal_ids": [str(item) for item in missing]},
        )


def _normalize_source_pairs(
    sources: Sequence[tuple[UUID, EvidenceSourceRole]],
) -> dict[UUID, EvidenceSourceRole]:
    result: dict[UUID, EvidenceSourceRole] = {}
    for signal_id, role in sources:
        existing = result.get(signal_id)
        if existing is not None and existing is not role:
            raise EvidenceSourceConflictError(
                "同一 Signal 不能同时作为 supporting 与 contradicting"
            )
        result[signal_id] = role
    return result


def _initial_state(
    sources: dict[UUID, EvidenceSourceRole],
) -> EvidenceVerificationState:
    support_count = sum(
        role is EvidenceSourceRole.SUPPORTING for role in sources.values()
    )
    contradiction_count = sum(
        role is EvidenceSourceRole.CONTRADICTING for role in sources.values()
    )
    if contradiction_count:
        return EvidenceVerificationState.DISPUTED
    if support_count == 1:
        return EvidenceVerificationState.SINGLE_SOURCE
    return EvidenceVerificationState.INVESTIGATING


def _normalized_optional(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = normalize_evidence_text(value)
    return normalized or None
