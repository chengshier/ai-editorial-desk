from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
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
    EditorialRecommendedFormat,
    EditorialRiskLevel,
    EditorialScoreOverrideRecord,
    EditorialScoreRecord,
    EditorialScoreSourceType,
    EditorialScoringMode,
    EditorialScoringRunRecord,
    EditorialScoringStatus,
    EventRecord,
    EventSignalRecord,
    EventSignalRelation,
    EventTrendSnapshotRecord,
    EvidenceClaimRecord,
    EvidenceVerificationState,
    RawSignalRecord,
)
from packages.database.session import get_async_sessionmaker
from packages.database.types import utc_now
from packages.editorial.domain import (
    DIMENSION_NAMES,
    EDITORIAL_PROMPT_VERSION,
    EDITORIAL_SCHEMA_NAME,
    EDITORIAL_SCHEMA_VERSION,
    EDITORIAL_SCORE_SCHEMA_V1,
    EDITORIAL_SCORE_TEMPLATE,
    EDITORIAL_SCORE_TEMPLATE_VERSION,
    EDITORIAL_SCORING_MAX_OUTPUT_TOKENS,
    EDITORIAL_SCORING_VERSION,
    GEOGRAPHY_UNAVAILABLE,
    INTERACTION_UNAVAILABLE,
    MAX_TREND_WINDOW_HOURS,
    MEDIA_UNAVAILABLE,
    SEMANTIC_NOVELTY_UNAVAILABLE,
    TREND_CALCULATION_VERSION,
    EditorialDimensions,
    EvidenceStateSummary,
    ValidatedEditorialCandidate,
    calculate_traffic_total,
    normalize_text,
    stable_hash,
    validate_ai_candidate,
    validate_dimensions,
)
from packages.editorial.errors import (
    EditorialEventMergedError,
    EditorialRiskConflictError,
    EditorialValidationError,
    TrendValidationError,
)
from packages.editorial.input_builder import (
    EditorialScoringInputBuilder,
    EditorialScoringSnapshot,
)
from packages.editorial.repositories import (
    EditorialOverrideRepository,
    EditorialScoreRepository,
    EditorialScoringRunRepository,
    TrendSnapshotRepository,
)


class StructuredGateway(Protocol):
    async def generate_structured(
        self,
        *,
        task_key: str,
        messages: tuple[AIMessage, ...],
        schema: dict[str, Any],
        schema_name: str,
        max_output_tokens: int | None = None,
        temperature: float | None = None,
        context: InvocationContext | None = None,
        invocation_id: UUID | None = None,
    ) -> GatewayStructuredResult: ...


@dataclass(frozen=True, slots=True)
class TrendCalculationOutcome:
    snapshot: EventTrendSnapshotRecord
    created: bool


@dataclass(frozen=True, slots=True)
class EditorialScoringOutcome:
    run_id: UUID | None
    ai_invocation_id: UUID | None
    mode: EditorialScoringMode
    status: EditorialScoringStatus
    score: EditorialScoreRecord | None
    candidate: ValidatedEditorialCandidate
    traffic_total: float
    reused: bool


@dataclass(frozen=True, slots=True)
class EffectiveEditorialAssessment:
    event_id: UUID
    latest_ai_score: EditorialScoreRecord | None
    latest_human_score: EditorialScoreRecord | None
    effective_base_score_id: UUID | None
    effective_values: dict[str, Any] | None
    applied_overrides: tuple[EditorialScoreOverrideRecord, ...]


class TrendService:
    """Deterministic M4-C trend calculation. No LLM/provider calls are allowed here."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self.session_factory = session_factory or get_async_sessionmaker()

    async def calculate(
        self,
        *,
        event_id: UUID,
        window_start_at: datetime,
        window_end_at: datetime,
    ) -> TrendCalculationOutcome:
        start = _require_aware_utc(window_start_at, "window_start_at")
        end = _require_aware_utc(window_end_at, "window_end_at")
        if end <= start:
            raise TrendValidationError("Trend window_end_at 必须晚于 window_start_at")
        window_hours = (end - start).total_seconds() / 3600.0
        if window_hours > MAX_TREND_WINDOW_HOURS:
            raise TrendValidationError(
                f"Trend 时间窗不得超过 {MAX_TREND_WINDOW_HOURS} 小时"
            )

        async with self.session_factory() as session:
            async with session.begin():
                event = await _require_active_event(session, event_id, for_update=True)
                membership_statement = (
                    select(EventSignalRecord, RawSignalRecord)
                    .join(
                        RawSignalRecord,
                        RawSignalRecord.id == EventSignalRecord.signal_id,
                    )
                    .where(EventSignalRecord.event_id == event_id)
                    .order_by(EventSignalRecord.signal_id.asc())
                )
                memberships = list((await session.execute(membership_statement)).all())

                claims = list(
                    (
                        await session.scalars(
                            select(EvidenceClaimRecord)
                            .where(EvidenceClaimRecord.event_id == event_id)
                            .order_by(EvidenceClaimRecord.id.asc())
                        )
                    ).all()
                )

                new_memberships = [
                    (link, signal)
                    for link, signal in memberships
                    if start <= _effective_time(signal) < end
                ]
                source_ids = {
                    signal.source_id
                    for _link, signal in memberships
                    if signal.source_id is not None
                }
                platforms = {signal.platform for _link, signal in memberships}
                new_claims = [
                    claim for claim in claims if start <= claim.created_at < end
                ]
                changed_supported_claims = [
                    claim
                    for claim in claims
                    if start <= claim.updated_at < end
                    and claim.verification_state
                    in (
                        EvidenceVerificationState.CONFIRMED,
                        EvidenceVerificationState.INVESTIGATING,
                    )
                ]
                official_response_count = sum(
                    link.relation is EventSignalRelation.OFFICIAL_RESPONSE
                    for link, _signal in new_memberships
                )
                correction_count = sum(
                    link.relation is EventSignalRelation.CORRECTION
                    for link, _signal in new_memberships
                )

                new_signal_count = len(new_memberships)
                signal_velocity = round(new_signal_count / window_hours, 6)
                update_value = float(
                    min(new_signal_count, 5) * 6
                    + min(len(new_claims), 2) * 10
                    + min(len(changed_supported_claims), 2) * 15
                    + min(official_response_count, 1) * 10
                    + min(correction_count, 1) * 10
                )
                availability = {
                    "signal_velocity": True,
                    "interaction_velocity": False,
                    "cross_source": True,
                    "cross_platform": True,
                    "semantic_novelty": False,
                    "cn_gap": False,
                    "update_value": True,
                    "media_availability": False,
                }
                component_metrics: dict[str, Any] = {
                    "window_hours": round(window_hours, 6),
                    "effective_time_rule": "published_at_else_collected_at",
                    "new_claim_count": len(new_claims),
                    "new_confirmed_or_investigating_claim_count": len(
                        changed_supported_claims
                    ),
                    "new_official_response_signal_count": official_response_count,
                    "correction_count": correction_count,
                    "update_value_formula": (
                        "min(new_signal_count,5)*6 + min(new_claim_count,2)*10 + "
                        "min(new_confirmed_or_investigating_claim_count,2)*15 + "
                        "min(new_official_response_signal_count,1)*10 + "
                        "min(correction_count,1)*10"
                    ),
                    "unavailable_reasons": {
                        "interaction_velocity": INTERACTION_UNAVAILABLE,
                        "cn_gap": GEOGRAPHY_UNAVAILABLE,
                        "semantic_novelty": SEMANTIC_NOVELTY_UNAVAILABLE,
                        "media_availability": MEDIA_UNAVAILABLE,
                    },
                }
                hash_payload = {
                    "event_id": str(event.id),
                    "calculation_version": TREND_CALCULATION_VERSION,
                    "window_start_at": start,
                    "window_end_at": end,
                    "memberships": [
                        {
                            "signal_id": str(signal.id),
                            "source_id": str(signal.source_id) if signal.source_id else None,
                            "platform": signal.platform,
                            "effective_time": _effective_time(signal),
                            "relation_type": link.relation.value,
                        }
                        for link, signal in memberships
                    ],
                    "claims": [
                        {
                            "claim_id": str(claim.id),
                            "verification_state": claim.verification_state.value,
                            "created_at": claim.created_at,
                            "updated_at": claim.updated_at,
                        }
                        for claim in claims
                        if (
                            start <= claim.created_at < end
                            or start <= claim.updated_at < end
                        )
                    ],
                }
                snapshot = EventTrendSnapshotRecord(
                    event_id=event_id,
                    calculation_version=TREND_CALCULATION_VERSION,
                    window_start_at=start,
                    window_end_at=end,
                    signal_count=len(memberships),
                    new_signal_count=new_signal_count,
                    source_count=len(source_ids),
                    platform_count=len(platforms),
                    signal_velocity=signal_velocity,
                    interaction_velocity=None,
                    cross_source=len(source_ids) > 1,
                    cross_platform=len(platforms) > 1,
                    semantic_novelty=None,
                    cn_gap=None,
                    update_value=update_value,
                    feature_availability=availability,
                    component_metrics=component_metrics,
                    input_hash=stable_hash(hash_payload),
                )
                persisted, created = await TrendSnapshotRepository(
                    session
                ).insert_if_absent(snapshot)
                return TrendCalculationOutcome(snapshot=persisted, created=created)

    async def latest(self, event_id: UUID) -> EventTrendSnapshotRecord | None:
        async with self.session_factory() as session:
            event = await session.get(EventRecord, event_id)
            if event is None:
                raise ResourceNotFoundError("事件不存在")
            return await TrendSnapshotRepository(session).latest_for_event(event_id)


class EditorialScoringService:
    """Versioned editorial semantic scoring through M4-A AIGateway."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        gateway: StructuredGateway | None = None,
    ) -> None:
        self.session_factory = session_factory or get_async_sessionmaker()
        self.gateway = gateway or AIGateway(session_factory=self.session_factory)
        self.input_builder = EditorialScoringInputBuilder(self.session_factory)

    async def score(
        self,
        *,
        event_id: UUID,
        trend_snapshot_id: UUID,
        actor: str,
        apply: bool,
    ) -> EditorialScoringOutcome:
        snapshot = await self.input_builder.build(
            event_id=event_id,
            trend_snapshot_id=trend_snapshot_id,
        )
        mode = EditorialScoringMode.APPLY if apply else EditorialScoringMode.PREVIEW

        if apply:
            existing = await self._existing_ai_score(snapshot)
            if existing is not None:
                candidate = _candidate_from_score(existing)
                return EditorialScoringOutcome(
                    run_id=existing.scoring_run_id,
                    ai_invocation_id=existing.ai_invocation_id,
                    mode=mode,
                    status=EditorialScoringStatus.SUCCEEDED,
                    score=existing,
                    candidate=candidate,
                    traffic_total=existing.traffic_total,
                    reused=True,
                )

        run = EditorialScoringRunRecord(
            event_id=event_id,
            trend_snapshot_id=trend_snapshot_id,
            ai_invocation_id=None,
            score_template=EDITORIAL_SCORE_TEMPLATE,
            score_template_version=EDITORIAL_SCORE_TEMPLATE_VERSION,
            scoring_version=EDITORIAL_SCORING_VERSION,
            prompt_version=EDITORIAL_PROMPT_VERSION,
            schema_version=EDITORIAL_SCHEMA_VERSION,
            mode=mode,
            status=EditorialScoringStatus.RUNNING,
            input_hash=snapshot.input_hash,
            requested_by=actor,
            error_code=None,
            error_summary=None,
            finished_at=None,
        )
        async with self.session_factory() as session:
            async with session.begin():
                EditorialScoringRunRepository(session).add(run)
                await session.flush()
                run_id = run.id

        invocation_id = uuid4()
        try:
            gateway_result = await self.gateway.generate_structured(
                task_key="editorial_scoring",
                messages=snapshot.messages(),
                schema=EDITORIAL_SCORE_SCHEMA_V1,
                schema_name=EDITORIAL_SCHEMA_NAME,
                max_output_tokens=EDITORIAL_SCORING_MAX_OUTPUT_TOKENS,
                temperature=0.0,
                context=InvocationContext(
                    prompt_version=EDITORIAL_PROMPT_VERSION,
                    schema_version=EDITORIAL_SCHEMA_VERSION,
                    subject_type="event",
                    subject_id=str(event_id),
                    metadata={
                        "editorial_scoring_run_id": str(run_id),
                        "trend_snapshot_id": str(trend_snapshot_id),
                        "score_template": EDITORIAL_SCORE_TEMPLATE,
                        "score_template_version": EDITORIAL_SCORE_TEMPLATE_VERSION,
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

        try:
            candidate = validate_ai_candidate(gateway_result.data)
            _enforce_ai_risk_guard(candidate, snapshot.evidence_summary)
        except (ValueError, EditorialRiskConflictError) as exc:
            await self._finish_failed_run(
                run_id=run_id,
                invocation_id=gateway_result.invocation_id,
                error_code=getattr(exc, "code", "EDITORIAL_OUTPUT_INVALID"),
                error_summary=str(exc),
            )
            if isinstance(exc, EditorialRiskConflictError):
                raise
            raise EditorialValidationError(str(exc)) from exc

        traffic_total = calculate_traffic_total(candidate.dimensions)
        if not apply:
            await self._finish_run(
                run_id=run_id,
                invocation_id=gateway_result.invocation_id,
                status=EditorialScoringStatus.SUCCEEDED,
            )
            return EditorialScoringOutcome(
                run_id=run_id,
                ai_invocation_id=gateway_result.invocation_id,
                mode=mode,
                status=EditorialScoringStatus.SUCCEEDED,
                score=None,
                candidate=candidate,
                traffic_total=traffic_total,
                reused=False,
            )

        score, created = await self._apply_ai_score(
            run_id=run_id,
            event_id=event_id,
            trend_snapshot_id=trend_snapshot_id,
            actor=actor,
            invocation_id=gateway_result.invocation_id,
            input_hash=snapshot.input_hash,
            candidate=candidate,
            traffic_total=traffic_total,
        )
        return EditorialScoringOutcome(
            run_id=run_id,
            ai_invocation_id=gateway_result.invocation_id,
            mode=mode,
            status=EditorialScoringStatus.SUCCEEDED,
            score=score,
            candidate=_candidate_from_score(score),
            traffic_total=score.traffic_total,
            reused=not created,
        )

    async def create_manual_score(
        self,
        *,
        event_id: UUID,
        trend_snapshot_id: UUID | None,
        actor: str,
        reason: str,
        dimensions: dict[str, Any],
        risk_level: EditorialRiskLevel,
        recommended_format: EditorialRecommendedFormat,
        model_reason: str | None = None,
    ) -> EditorialScoreRecord:
        normalized_reason = normalize_text(reason)
        if not normalized_reason:
            raise EditorialValidationError("人工评分必须提供 reason")
        normalized_actor = normalize_text(actor)
        if not normalized_actor:
            raise EditorialValidationError("人工评分必须提供 Actor")
        try:
            parsed_dimensions = validate_dimensions(dimensions)
        except ValueError as exc:
            raise EditorialValidationError(str(exc)) from exc

        traffic_total = calculate_traffic_total(parsed_dimensions)
        input_hash = stable_hash(
            {
                "source_type": "human",
                "event_id": str(event_id),
                "trend_snapshot_id": str(trend_snapshot_id) if trend_snapshot_id else None,
                "score_template": EDITORIAL_SCORE_TEMPLATE,
                "score_template_version": EDITORIAL_SCORE_TEMPLATE_VERSION,
                "scoring_version": EDITORIAL_SCORING_VERSION,
                "dimensions": parsed_dimensions.as_dict(),
                "risk_level": risk_level.value,
                "recommended_format": recommended_format.value,
                "reason": normalized_reason,
            }
        )

        async with self.session_factory() as session:
            async with session.begin():
                await _require_active_event(session, event_id, for_update=True)
                if trend_snapshot_id is not None:
                    await _require_trend_snapshot(session, event_id, trend_snapshot_id)
                score = EditorialScoreRecord(
                    event_id=event_id,
                    trend_snapshot_id=trend_snapshot_id,
                    score_template=EDITORIAL_SCORE_TEMPLATE,
                    score_template_version=EDITORIAL_SCORE_TEMPLATE_VERSION,
                    scoring_version=EDITORIAL_SCORING_VERSION,
                    source_type=EditorialScoreSourceType.HUMAN,
                    **parsed_dimensions.as_dict(),
                    traffic_total=traffic_total,
                    risk_level=risk_level,
                    recommended_format=recommended_format,
                    model_reason=normalize_text(model_reason or "") or None,
                    ai_invocation_id=None,
                    scoring_run_id=None,
                    input_hash=input_hash,
                    created_by_actor=normalized_actor,
                    source_reason=normalized_reason,
                )
                EditorialScoreRepository(session).add_human(score)
                await session.flush()
                AuditLogRepository(session).add(
                    entity_type="editorial_score",
                    entity_id=score.id,
                    action="human_create",
                    actor=normalized_actor,
                    before_data={},
                    after_data={
                        "event_id": str(event_id),
                        "source_type": "human",
                        "traffic_total": traffic_total,
                        "risk_level": risk_level.value,
                        "recommended_format": recommended_format.value,
                        "reason": normalized_reason,
                    },
                )
                return score

    async def override_score(
        self,
        *,
        event_id: UUID,
        score_id: UUID,
        actor: str,
        reason: str,
        overridden_fields: dict[str, Any],
    ) -> EditorialScoreOverrideRecord:
        normalized_reason = normalize_text(reason)
        normalized_actor = normalize_text(actor)
        if not normalized_actor or not normalized_reason:
            raise EditorialValidationError("Human override 必须包含 Actor 与 reason")
        normalized_fields = _validate_override_fields(overridden_fields)
        async with self.session_factory() as session:
            async with session.begin():
                await _require_active_event(session, event_id, for_update=True)
                score = await EditorialScoreRepository(session).get(score_id)
                if score is None or score.event_id != event_id:
                    raise ResourceNotFoundError("Editorial Score 不存在")
                override = EditorialScoreOverrideRecord(
                    editorial_score_id=score.id,
                    overridden_fields=normalized_fields,
                    reason=normalized_reason,
                    actor=normalized_actor,
                )
                EditorialOverrideRepository(session).add(override)
                await session.flush()
                AuditLogRepository(session).add(
                    entity_type="editorial_score_override",
                    entity_id=override.id,
                    action="human_override",
                    actor=normalized_actor,
                    before_data={"editorial_score_id": str(score.id)},
                    after_data={
                        "overridden_fields": normalized_fields,
                        "reason": normalized_reason,
                    },
                )
                return override

    async def list_scores(self, event_id: UUID) -> tuple[EditorialScoreRecord, ...]:
        async with self.session_factory() as session:
            event = await session.get(EventRecord, event_id)
            if event is None:
                raise ResourceNotFoundError("事件不存在")
            return tuple(await EditorialScoreRepository(session).list_for_event(event_id))

    async def effective(self, event_id: UUID) -> EffectiveEditorialAssessment:
        async with self.session_factory() as session:
            event = await session.get(EventRecord, event_id)
            if event is None:
                raise ResourceNotFoundError("事件不存在")
            score_repo = EditorialScoreRepository(session)
            latest_ai = await score_repo.latest_ai_for_event(event_id)
            latest_human = await score_repo.latest_human_for_event(event_id)
            overrides = tuple(
                await EditorialOverrideRepository(session).list_for_event(event_id)
            )
            base = latest_human or latest_ai
            if base is None:
                return EffectiveEditorialAssessment(
                    event_id=event_id,
                    latest_ai_score=latest_ai,
                    latest_human_score=latest_human,
                    effective_base_score_id=None,
                    effective_values=None,
                    applied_overrides=overrides,
                )
            effective = _score_values(base)
            for override in overrides:
                effective.update(override.overridden_fields)
            dimensions = validate_dimensions(effective)
            effective["traffic_total"] = calculate_traffic_total(dimensions)
            return EffectiveEditorialAssessment(
                event_id=event_id,
                latest_ai_score=latest_ai,
                latest_human_score=latest_human,
                effective_base_score_id=base.id,
                effective_values=effective,
                applied_overrides=overrides,
            )

    async def _existing_ai_score(
        self,
        snapshot: EditorialScoringSnapshot,
    ) -> EditorialScoreRecord | None:
        async with self.session_factory() as session:
            return await EditorialScoreRepository(session).get_ai_by_input(
                event_id=snapshot.event_id,
                score_template=EDITORIAL_SCORE_TEMPLATE,
                score_template_version=EDITORIAL_SCORE_TEMPLATE_VERSION,
                scoring_version=EDITORIAL_SCORING_VERSION,
                input_hash=snapshot.input_hash,
            )

    async def _apply_ai_score(
        self,
        *,
        run_id: UUID,
        event_id: UUID,
        trend_snapshot_id: UUID,
        actor: str,
        invocation_id: UUID,
        input_hash: str,
        candidate: ValidatedEditorialCandidate,
        traffic_total: float,
    ) -> tuple[EditorialScoreRecord, bool]:
        async with self.session_factory() as session:
            async with session.begin():
                await _require_active_event(session, event_id, for_update=True)
                await _require_trend_snapshot(session, event_id, trend_snapshot_id)
                run = await EditorialScoringRunRepository(session).get_for_update(run_id)
                if run is None:
                    raise RuntimeError("EditorialScoringRun 不存在")
                score, created = await EditorialScoreRepository(session).insert_ai_if_absent(
                    values={
                        "event_id": event_id,
                        "trend_snapshot_id": trend_snapshot_id,
                        "score_template": EDITORIAL_SCORE_TEMPLATE,
                        "score_template_version": EDITORIAL_SCORE_TEMPLATE_VERSION,
                        "scoring_version": EDITORIAL_SCORING_VERSION,
                        "source_type": EditorialScoreSourceType.AI,
                        **candidate.dimensions.as_dict(),
                        "traffic_total": traffic_total,
                        "risk_level": candidate.risk_level,
                        "recommended_format": candidate.recommended_format,
                        "model_reason": candidate.model_reason,
                        "ai_invocation_id": invocation_id,
                        "scoring_run_id": run_id,
                        "input_hash": input_hash,
                        "created_by_actor": actor,
                        "source_reason": None,
                    }
                )
                run.ai_invocation_id = invocation_id
                run.status = EditorialScoringStatus.SUCCEEDED
                run.finished_at = utc_now()
                await session.flush()
                return score, created

    async def _finish_run(
        self,
        *,
        run_id: UUID,
        invocation_id: UUID,
        status: EditorialScoringStatus,
    ) -> None:
        async with self.session_factory() as session:
            async with session.begin():
                run = await EditorialScoringRunRepository(session).get_for_update(run_id)
                if run is None:
                    raise RuntimeError("EditorialScoringRun 不存在")
                run.ai_invocation_id = invocation_id
                run.status = status
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
                run = await EditorialScoringRunRepository(session).get_for_update(run_id)
                if run is None:
                    return
                invocation = await session.get(AIInvocationRecord, invocation_id)
                run.ai_invocation_id = invocation.id if invocation is not None else None
                run.status = EditorialScoringStatus.FAILED
                run.error_code = error_code[:100]
                run.error_summary = error_summary[:1000]
                run.finished_at = utc_now()


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
        raise EditorialEventMergedError(event.merged_into_event_id)
    return event


async def _require_trend_snapshot(
    session: AsyncSession,
    event_id: UUID,
    trend_snapshot_id: UUID,
) -> EventTrendSnapshotRecord:
    snapshot = await session.get(EventTrendSnapshotRecord, trend_snapshot_id)
    if snapshot is None or snapshot.event_id != event_id:
        raise ResourceNotFoundError("Trend Snapshot 不存在")
    return snapshot


def _effective_time(signal: RawSignalRecord) -> datetime:
    return signal.published_at or signal.collected_at


def _require_aware_utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise TrendValidationError(f"{field} 必须是带时区时间")
    return value.astimezone(UTC)


def _enforce_ai_risk_guard(
    candidate: ValidatedEditorialCandidate,
    summary: EvidenceStateSummary,
) -> None:
    if candidate.risk_level is not EditorialRiskLevel.R0:
        return
    if summary.claim_count == 0:
        raise EditorialRiskConflictError("无 Evidence 时 AI 不得给出 R0")
    if summary.confirmed_count == 0:
        raise EditorialRiskConflictError("没有 confirmed Claim 时 AI 不得给出 R0")
    if (
        summary.single_source_count + summary.disputed_count == summary.claim_count
    ):
        raise EditorialRiskConflictError(
            "全部 Evidence 为 single_source/disputed 时 AI 不得给出 R0"
        )
    if summary.open_unknown_count > 0:
        raise EditorialRiskConflictError(
            "仍存在未解决 Unknown 时 AI 不得给出 R0"
        )


def _validate_override_fields(values: dict[str, Any]) -> dict[str, Any]:
    if not values:
        raise EditorialValidationError("Override 至少需要一个字段")
    allowed = set(DIMENSION_NAMES) | {"risk_level", "recommended_format"}
    unknown = sorted(set(values) - allowed)
    if unknown:
        raise EditorialValidationError(
            "Override 包含不支持字段",
            details={"fields": unknown},
        )
    result: dict[str, Any] = {}
    for name in DIMENSION_NAMES:
        if name not in values:
            continue
        value = values[name]
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
            raise EditorialValidationError(f"{name} 必须是 0..100 integer")
        result[name] = value
    if "risk_level" in values:
        try:
            result["risk_level"] = EditorialRiskLevel(str(values["risk_level"])).value
        except ValueError as exc:
            raise EditorialValidationError("risk_level 必须是 R0..R4") from exc
    if "recommended_format" in values:
        try:
            result["recommended_format"] = EditorialRecommendedFormat(
                str(values["recommended_format"])
            ).value
        except ValueError as exc:
            raise EditorialValidationError("recommended_format 不受支持") from exc
    return result


def _candidate_from_score(score: EditorialScoreRecord) -> ValidatedEditorialCandidate:
    return ValidatedEditorialCandidate(
        dimensions=EditorialDimensions(
            emotion=score.emotion,
            information_gap=score.information_gap,
            visual_value=score.visual_value,
            user_relevance=score.user_relevance,
            discussion=score.discussion,
            novelty=score.novelty,
            extendability=score.extendability,
        ),
        risk_level=score.risk_level,
        recommended_format=score.recommended_format,
        model_reason=score.model_reason or score.source_reason or "",
    )


def _score_values(score: EditorialScoreRecord) -> dict[str, Any]:
    return {
        "emotion": score.emotion,
        "information_gap": score.information_gap,
        "visual_value": score.visual_value,
        "user_relevance": score.user_relevance,
        "discussion": score.discussion,
        "novelty": score.novelty,
        "extendability": score.extendability,
        "traffic_total": score.traffic_total,
        "risk_level": score.risk_level.value,
        "recommended_format": score.recommended_format.value,
    }
