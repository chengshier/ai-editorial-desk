from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.clustering.policy import DEFAULT_CLUSTER_POLICY, ClusterPolicy
from packages.clustering.provenance import (
    ClusteringProcessingRunRepository,
    EventAssignmentRepository,
)
from packages.clustering.repositories import (
    ClusteringQueryRepository,
    MatchDecisionRepository,
    MatchOverrideRepository,
    SignalEventSuppressionRepository,
)
from packages.clustering.services import (
    ClusterOutcomeStatus,
    EventClusteringService,
    MatchDecision,
    SignalMatchService,
)
from packages.connector_management.exceptions import (
    BusinessValidationError,
    ResourceNotFoundError,
)
from packages.connector_management.repositories import AuditLogRepository
from packages.database.models import (
    ClusteringProcessingMode,
    ClusteringProcessingStatus,
    EventAssignmentAction,
    EventRecord,
    EventSignalAttachedBy,
    EventSignalRecord,
    EventSignalRelation,
    MatchDecisionType,
    MatchOverrideDecision,
    MatchPrimaryMethod,
    RawSignalRecord,
)
from packages.database.types import utc_now
from packages.events.repositories import EventRepository, EventSignalRepository


class ReprocessAction(StrEnum):
    ATTACH = "attach"
    CREATE_EVENT = "create_event"
    MOVE = "move"
    AMBIGUOUS = "ambiguous"
    SKIPPED_HUMAN = "skipped_human"
    SUPPRESSED = "suppressed"
    UNCHANGED = "unchanged"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ReprocessPlan:
    signal_id: UUID
    action: ReprocessAction
    code: str
    current_event_id: UUID | None = None
    target_event_id: UUID | None = None
    candidate_signal_id: UUID | None = None
    decision: MatchDecisionType | None = None
    score: float | None = None
    attached_by: EventSignalAttachedBy | None = None


@dataclass(frozen=True, slots=True)
class ReprocessSummary:
    processing_run_id: UUID | None
    algorithm_version: str
    dry_run: bool
    scanned: int
    would_attach: int
    would_create_event: int
    would_move: int
    would_detach: int
    ambiguous: int
    skipped_human: int
    suppressed: int
    unchanged: int
    failed: int
    outcomes: tuple[ReprocessPlan, ...]

    def counters(self) -> dict[str, int]:
        return {
            "scanned": self.scanned,
            "would_attach": self.would_attach,
            "would_create_event": self.would_create_event,
            "would_move": self.would_move,
            "would_detach": self.would_detach,
            "ambiguous": self.ambiguous,
            "skipped_human": self.skipped_human,
            "suppressed": self.suppressed,
            "unchanged": self.unchanged,
            "failed": self.failed,
        }


class ClusteringReprocessService:
    """Bounded, dry-run-first replay that never overrides higher-priority human state."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        policy: ClusterPolicy = DEFAULT_CLUSTER_POLICY,
    ) -> None:
        self.session = session
        self.policy = policy
        self.matcher = SignalMatchService(session, policy=policy)
        self.queries = ClusteringQueryRepository(session)
        self.suppressions = SignalEventSuppressionRepository(session)
        self.overrides = MatchOverrideRepository(session)
        self.decisions = MatchDecisionRepository(session)
        self.events = EventRepository(session)
        self.event_signals = EventSignalRepository(session)
        self.runs = ClusteringProcessingRunRepository(session)
        self.assignments = EventAssignmentRepository(session)
        self.audit = AuditLogRepository(session)

    async def reprocess(
        self,
        *,
        signal_ids: list[UUID] | None,
        time_from: datetime | None,
        time_to: datetime | None,
        algorithm_version: str,
        embedding_version: str | None,
        max_items: int,
        actor: str | None,
        apply: bool = False,
        confirmed: bool = False,
    ) -> ReprocessSummary:
        self._validate_request(
            signal_ids=signal_ids,
            time_from=time_from,
            time_to=time_to,
            algorithm_version=algorithm_version,
            max_items=max_items,
            actor=actor,
            apply=apply,
            confirmed=confirmed,
        )
        target_ids = await self._resolve_targets(
            signal_ids=signal_ids,
            time_from=time_from,
            time_to=time_to,
            max_items=max_items,
        )
        run = await self._start_run(
            target_ids=target_ids,
            signal_ids=signal_ids,
            time_from=time_from,
            time_to=time_to,
            algorithm_version=algorithm_version,
            embedding_version=embedding_version,
            max_items=max_items,
            actor=actor,
            apply=apply,
        )
        plans: list[ReprocessPlan] = []
        for signal_id in target_ids:
            try:
                plan = await self._plan_signal(
                    signal_id=signal_id,
                    embedding_version=embedding_version,
                )
                if apply:
                    plan = await self._apply_plan(
                        plan,
                        embedding_version=embedding_version,
                        actor=actor or "",
                        processing_run_id=run.id,
                    )
            except (BusinessValidationError, ResourceNotFoundError) as exc:
                plan = ReprocessPlan(
                    signal_id=signal_id,
                    action=ReprocessAction.FAILED,
                    code=type(exc).__name__,
                )
            plans.append(plan)
        summary = self._summarize(
            run_id=run.id,
            algorithm_version=algorithm_version,
            dry_run=not apply,
            plans=plans,
        )
        await self._finish_run(run, summary)
        return summary

    def _validate_request(
        self,
        *,
        signal_ids: list[UUID] | None,
        time_from: datetime | None,
        time_to: datetime | None,
        algorithm_version: str,
        max_items: int,
        actor: str | None,
        apply: bool,
        confirmed: bool,
    ) -> None:
        if algorithm_version != self.policy.algorithm_version:
            raise BusinessValidationError("algorithm_version 未注册或与当前 policy 不匹配")
        if max_items < 1 or max_items > self.policy.max_batch_size:
            raise BusinessValidationError(
                f"max_items 必须在 1 到 {self.policy.max_batch_size} 之间"
            )
        explicit = bool(signal_ids)
        ranged = time_from is not None or time_to is not None
        if explicit == ranged:
            raise BusinessValidationError("必须且只能指定 signal_ids 或完整 time range")
        if explicit and len(set(signal_ids or [])) > max_items:
            raise BusinessValidationError("signal_ids 数量不能超过 max_items")
        if ranged:
            if time_from is None or time_to is None:
                raise BusinessValidationError("time range 必须同时提供 from/to")
            if (
                time_from.tzinfo is None
                or time_from.utcoffset() is None
                or time_to.tzinfo is None
                or time_to.utcoffset() is None
            ):
                raise BusinessValidationError("time range 必须使用带时区时间")
            if time_from >= time_to:
                raise BusinessValidationError("time_from 必须早于 time_to")
        if apply:
            if not actor or not actor.strip():
                raise BusinessValidationError("apply 必须提供 actor")
            if not confirmed:
                raise BusinessValidationError("apply 必须显式 confirmation")

    async def _resolve_targets(
        self,
        *,
        signal_ids: list[UUID] | None,
        time_from: datetime | None,
        time_to: datetime | None,
        max_items: int,
    ) -> list[UUID]:
        if signal_ids:
            return sorted(set(signal_ids), key=lambda value: value.int)
        assert time_from is not None and time_to is not None
        effective_time = func.coalesce(
            RawSignalRecord.published_at,
            RawSignalRecord.collected_at,
        )
        async with self.session.begin():
            statement = (
                select(RawSignalRecord.id)
                .where(effective_time >= time_from, effective_time <= time_to)
                .order_by(effective_time.asc(), RawSignalRecord.id.asc())
                .limit(max_items)
            )
            return list((await self.session.scalars(statement)).all())

    async def _start_run(
        self,
        *,
        target_ids: list[UUID],
        signal_ids: list[UUID] | None,
        time_from: datetime | None,
        time_to: datetime | None,
        algorithm_version: str,
        embedding_version: str | None,
        max_items: int,
        actor: str | None,
        apply: bool,
    ):  # type: ignore[no-untyped-def]
        config_snapshot: dict[str, object] = {
            "target_kind": "signal_ids" if signal_ids else "time_range",
            "signal_count": len(signal_ids or []),
            "time_from": time_from.isoformat() if time_from else None,
            "time_to": time_to.isoformat() if time_to else None,
            "embedding_version": embedding_version,
            "max_items": max_items,
            "dry_run": not apply,
        }
        async with self.session.begin():
            return await self.runs.create(
                mode=(
                    ClusteringProcessingMode.APPLY
                    if apply
                    else ClusteringProcessingMode.DRY_RUN
                ),
                algorithm_version=algorithm_version,
                dataset_version=None,
                actor=actor,
                requested_count=len(target_ids),
                config_snapshot=config_snapshot,
            )

    async def _finish_run(self, run, summary: ReprocessSummary) -> None:  # type: ignore[no-untyped-def]
        status = (
            ClusteringProcessingStatus.SUCCEEDED
            if summary.failed == 0
            else ClusteringProcessingStatus.PARTIAL
            if summary.failed < summary.scanned
            else ClusteringProcessingStatus.FAILED
        )
        async with self.session.begin():
            await self.runs.finish(
                run,
                status=status,
                processed_count=summary.scanned,
                counters=summary.counters(),
            )

    async def _plan_signal(
        self,
        *,
        signal_id: UUID,
        embedding_version: str | None,
    ) -> ReprocessPlan:
        preview = await self.matcher.preview(
            signal_id=signal_id,
            embedding_version=embedding_version,
        )
        async with self.session.begin():
            target = await self.session.get(RawSignalRecord, signal_id)
            if target is None:
                raise ResourceNotFoundError("原始信号不存在")
            memberships = await self.queries.active_memberships(signal_id)
            human_memberships = [
                item
                for item in memberships
                if item.attached_by is EventSignalAttachedBy.HUMAN
            ]
            if human_memberships:
                return ReprocessPlan(
                    signal_id=signal_id,
                    action=ReprocessAction.SKIPPED_HUMAN,
                    code="HUMAN_MEMBERSHIP_PRESERVED",
                    current_event_id=human_memberships[0].event_id,
                )
            if len(memberships) > 1:
                return ReprocessPlan(
                    signal_id=signal_id,
                    action=ReprocessAction.AMBIGUOUS,
                    code="MULTIPLE_ACTIVE_MEMBERSHIPS",
                )
            current = memberships[0] if memberships else None
            candidate_events = await self._candidate_events(preview.decisions)
            if len(candidate_events) > 1:
                return ReprocessPlan(
                    signal_id=signal_id,
                    action=ReprocessAction.AMBIGUOUS,
                    code="MULTIPLE_CANDIDATE_EVENTS",
                    current_event_id=current.event_id if current else None,
                )
            if len(candidate_events) == 1:
                candidate_event_id = next(iter(candidate_events))
                if await self.suppressions.is_active(signal_id, candidate_event_id):
                    return ReprocessPlan(
                        signal_id=signal_id,
                        action=ReprocessAction.SUPPRESSED,
                        code="HUMAN_EVENT_SUPPRESSION",
                        current_event_id=current.event_id if current else None,
                        target_event_id=candidate_event_id,
                    )
                best = max(
                    candidate_events[candidate_event_id],
                    key=lambda item: (item.score, -item.candidate_signal_id.int),
                )
                attached_by = self._attached_by(best)
                if current is None:
                    return ReprocessPlan(
                        signal_id=signal_id,
                        action=ReprocessAction.ATTACH,
                        code="WOULD_ATTACH",
                        target_event_id=candidate_event_id,
                        candidate_signal_id=best.candidate_signal_id,
                        decision=best.decision,
                        score=best.score,
                        attached_by=attached_by,
                    )
                canonical_event_id = min(
                    (current.event_id, candidate_event_id),
                    key=lambda value: value.int,
                )
                if canonical_event_id == current.event_id:
                    return ReprocessPlan(
                        signal_id=signal_id,
                        action=ReprocessAction.UNCHANGED,
                        code="CANONICAL_EVENT_ALREADY_SELECTED",
                        current_event_id=current.event_id,
                        target_event_id=current.event_id,
                    )
                if await self._event_has_human_membership(current.event_id):
                    return ReprocessPlan(
                        signal_id=signal_id,
                        action=ReprocessAction.AMBIGUOUS,
                        code="HUMAN_OVERRIDE_CONFLICT",
                        current_event_id=current.event_id,
                        target_event_id=canonical_event_id,
                    )
                if await self._has_distinct_override_to_event(
                    signal_id,
                    canonical_event_id,
                ):
                    return ReprocessPlan(
                        signal_id=signal_id,
                        action=ReprocessAction.AMBIGUOUS,
                        code="HUMAN_OVERRIDE_CONFLICT",
                        current_event_id=current.event_id,
                        target_event_id=canonical_event_id,
                    )
                return ReprocessPlan(
                    signal_id=signal_id,
                    action=ReprocessAction.MOVE,
                    code="WOULD_MOVE_AUTO_MEMBERSHIP",
                    current_event_id=current.event_id,
                    target_event_id=canonical_event_id,
                    candidate_signal_id=best.candidate_signal_id,
                    decision=best.decision,
                    score=best.score,
                    attached_by=attached_by,
                )
            if any(
                item.decision is MatchDecisionType.AMBIGUOUS
                for item in preview.decisions
            ):
                return ReprocessPlan(
                    signal_id=signal_id,
                    action=ReprocessAction.AMBIGUOUS,
                    code="AMBIGUOUS_MATCH_REQUIRES_REVIEW",
                    current_event_id=current.event_id if current else None,
                )
            if current is not None:
                return ReprocessPlan(
                    signal_id=signal_id,
                    action=ReprocessAction.UNCHANGED,
                    code="NO_AUTOMATIC_DETACH_POLICY",
                    current_event_id=current.event_id,
                )
            if not ((target.title or "").strip() or (target.text or "").strip()):
                return ReprocessPlan(
                    signal_id=signal_id,
                    action=ReprocessAction.UNCHANGED,
                    code="NO_EVENT_TITLE_TEXT",
                )
            return ReprocessPlan(
                signal_id=signal_id,
                action=ReprocessAction.CREATE_EVENT,
                code="WOULD_CREATE_EVENT",
            )

    async def _candidate_events(
        self,
        decisions: tuple[MatchDecision, ...],
    ) -> dict[UUID, list[MatchDecision]]:
        positive = {
            MatchDecisionType.EXACT_DUPLICATE,
            MatchDecisionType.NEAR_DUPLICATE,
            MatchDecisionType.SAME_EVENT,
        }
        result: dict[UUID, list[MatchDecision]] = {}
        for decision in decisions:
            if decision.decision not in positive:
                continue
            memberships = await self.queries.active_memberships(decision.candidate_signal_id)
            if len(memberships) != 1:
                continue
            result.setdefault(memberships[0].event_id, []).append(decision)
        return result

    async def _event_has_human_membership(self, event_id: UUID) -> bool:
        statement = select(EventSignalRecord.id).where(
            EventSignalRecord.event_id == event_id,
            EventSignalRecord.attached_by == EventSignalAttachedBy.HUMAN,
        )
        return (await self.session.scalar(statement)) is not None

    async def _has_distinct_override_to_event(
        self,
        signal_id: UUID,
        event_id: UUID,
    ) -> bool:
        for candidate_id in await self.queries.event_signal_ids(event_id):
            if candidate_id == signal_id:
                continue
            override = await self.overrides.get(signal_id, candidate_id)
            if override is not None and override.decision is MatchOverrideDecision.DISTINCT:
                return True
        return False

    @staticmethod
    def _attached_by(decision: MatchDecision) -> EventSignalAttachedBy:
        if decision.primary_method is MatchPrimaryMethod.HUMAN:
            return EventSignalAttachedBy.HUMAN
        if decision.decision in {
            MatchDecisionType.EXACT_DUPLICATE,
            MatchDecisionType.NEAR_DUPLICATE,
        }:
            return EventSignalAttachedBy.RULE
        return EventSignalAttachedBy.EMBEDDING

    async def _apply_plan(
        self,
        plan: ReprocessPlan,
        *,
        embedding_version: str | None,
        actor: str,
        processing_run_id: UUID,
    ) -> ReprocessPlan:
        if plan.action in {ReprocessAction.ATTACH, ReprocessAction.CREATE_EVENT}:
            outcome = await EventClusteringService(
                self.session,
                policy=self.policy,
            ).cluster_signal(
                signal_id=plan.signal_id,
                embedding_version=embedding_version,
                actor=actor,
            )
            if outcome.status in {
                ClusterOutcomeStatus.ATTACHED,
                ClusterOutcomeStatus.CREATED_EVENT,
            }:
                await self._record_standard_assignment(
                    plan=plan,
                    event_id=outcome.event_id,
                    processing_run_id=processing_run_id,
                )
                return ReprocessPlan(
                    signal_id=plan.signal_id,
                    action=plan.action,
                    code="APPLIED_" + plan.action.value.upper(),
                    target_event_id=outcome.event_id,
                    candidate_signal_id=plan.candidate_signal_id,
                    decision=plan.decision,
                    score=plan.score,
                    attached_by=plan.attached_by,
                )
            return ReprocessPlan(
                signal_id=plan.signal_id,
                action=ReprocessAction.AMBIGUOUS,
                code=outcome.code,
                current_event_id=outcome.event_id,
            )
        if plan.action is ReprocessAction.MOVE:
            return await self._apply_move(
                plan,
                actor=actor,
                processing_run_id=processing_run_id,
            )
        return plan

    async def _record_standard_assignment(
        self,
        *,
        plan: ReprocessPlan,
        event_id: UUID | None,
        processing_run_id: UUID,
    ) -> None:
        if event_id is None:
            return
        async with self.session.begin():
            association = await self.event_signals.get(event_id, plan.signal_id)
            if association is None:
                raise ResourceNotFoundError("apply 后 EventSignal 不存在")
            decision_id = await self._decision_id(plan)
            await self.assignments.add(
                signal_id=plan.signal_id,
                event_id=event_id,
                action=(
                    EventAssignmentAction.ATTACH
                    if plan.action is ReprocessAction.ATTACH
                    else EventAssignmentAction.CREATE_EVENT
                ),
                attached_by=association.attached_by,
                algorithm_version=self.policy.algorithm_version,
                match_decision_id=decision_id,
                processing_run_id=processing_run_id,
            )

    async def _decision_id(self, plan: ReprocessPlan) -> UUID | None:
        if plan.candidate_signal_id is None or plan.attached_by is EventSignalAttachedBy.HUMAN:
            return None
        record = await self.decisions.get(
            plan.signal_id,
            plan.candidate_signal_id,
            self.policy.algorithm_version,
        )
        return record.id if record is not None else None

    async def _apply_move(
        self,
        plan: ReprocessPlan,
        *,
        actor: str,
        processing_run_id: UUID,
    ) -> ReprocessPlan:
        if plan.current_event_id is None or plan.target_event_id is None:
            raise BusinessValidationError("move plan 缺少 Event 边界")
        async with self.session.begin():
            target_signal = await self.queries.get_signal_for_update(plan.signal_id)
            if target_signal is None:
                raise ResourceNotFoundError("原始信号不存在")
            memberships = await self.queries.active_memberships(plan.signal_id)
            if len(memberships) != 1:
                raise BusinessValidationError("apply 前 membership 已变化")
            association = memberships[0]
            if association.attached_by is EventSignalAttachedBy.HUMAN:
                raise BusinessValidationError("HUMAN_MEMBERSHIP_PRESERVED")
            if association.event_id != plan.current_event_id:
                raise BusinessValidationError("apply 前 membership 已被其他处理修改")
            locked = await self.queries.lock_events(
                [plan.current_event_id, plan.target_event_id]
            )
            locked_by_id = {event.id: event for event in locked}
            current_event = locked_by_id.get(plan.current_event_id)
            target_event = locked_by_id.get(plan.target_event_id)
            if current_event is None or target_event is None:
                raise ResourceNotFoundError("move Event 不存在")
            if target_event.merged_into_event_id is not None:
                raise BusinessValidationError("目标 Event 已被人工合并")
            if await self.suppressions.is_active(plan.signal_id, target_event.id):
                raise BusinessValidationError("HUMAN_EVENT_SUPPRESSION")
            if await self._event_has_human_membership(current_event.id):
                raise BusinessValidationError("HUMAN_OVERRIDE_CONFLICT")
            if await self._has_distinct_override_to_event(plan.signal_id, target_event.id):
                raise BusinessValidationError("HUMAN_OVERRIDE_CONFLICT")
            decision_id = await self._decision_id(plan)
            association.event_id = target_event.id
            association.relation = EventSignalRelation.RELATED
            association.confidence = (
                plan.score if plan.score is not None else association.confidence
            )
            association.attached_by = plan.attached_by or association.attached_by
            await self.session.flush()
            await self._recalculate_event(current_event)
            await self._recalculate_event(target_event)
            now = utc_now()
            current_event.last_updated_at = now
            target_event.last_updated_at = now
            await self.assignments.add(
                signal_id=plan.signal_id,
                event_id=target_event.id,
                previous_event_id=current_event.id,
                action=EventAssignmentAction.MOVE,
                attached_by=association.attached_by,
                algorithm_version=self.policy.algorithm_version,
                match_decision_id=decision_id,
                processing_run_id=processing_run_id,
            )
            self.audit.add(
                entity_type="event",
                entity_id=target_event.id,
                action="cluster_reprocess_move",
                actor=actor,
                before_data={
                    "signal_id": str(plan.signal_id),
                    "event_id": str(current_event.id),
                },
                after_data={
                    "signal_id": str(plan.signal_id),
                    "event_id": str(target_event.id),
                    "algorithm_version": self.policy.algorithm_version,
                    "processing_run_id": str(processing_run_id),
                },
            )
        return ReprocessPlan(
            signal_id=plan.signal_id,
            action=ReprocessAction.MOVE,
            code="APPLIED_MOVE",
            current_event_id=plan.current_event_id,
            target_event_id=plan.target_event_id,
            candidate_signal_id=plan.candidate_signal_id,
            decision=plan.decision,
            score=plan.score,
            attached_by=plan.attached_by,
        )

    async def _recalculate_event(self, event: EventRecord) -> None:
        source_count, platform_count, first_seen_at = (
            await self.event_signals.aggregate_stats(event.id)
        )
        event.source_count = source_count
        event.platform_count = platform_count
        event.first_seen_at = first_seen_at

    @staticmethod
    def _summarize(
        *,
        run_id: UUID,
        algorithm_version: str,
        dry_run: bool,
        plans: list[ReprocessPlan],
    ) -> ReprocessSummary:
        return ReprocessSummary(
            processing_run_id=run_id,
            algorithm_version=algorithm_version,
            dry_run=dry_run,
            scanned=len(plans),
            would_attach=sum(item.action is ReprocessAction.ATTACH for item in plans),
            would_create_event=sum(
                item.action is ReprocessAction.CREATE_EVENT for item in plans
            ),
            would_move=sum(item.action is ReprocessAction.MOVE for item in plans),
            would_detach=0,
            ambiguous=sum(item.action is ReprocessAction.AMBIGUOUS for item in plans),
            skipped_human=sum(
                item.action is ReprocessAction.SKIPPED_HUMAN for item in plans
            ),
            suppressed=sum(item.action is ReprocessAction.SUPPRESSED for item in plans),
            unchanged=sum(item.action is ReprocessAction.UNCHANGED for item in plans),
            failed=sum(item.action is ReprocessAction.FAILED for item in plans),
            outcomes=tuple(plans),
        )

    @staticmethod
    def summary_payload(summary: ReprocessSummary) -> dict[str, object]:
        return {
            **summary.counters(),
            "processing_run_id": str(summary.processing_run_id)
            if summary.processing_run_id
            else None,
            "algorithm_version": summary.algorithm_version,
            "dry_run": summary.dry_run,
            "outcomes": [asdict(item) for item in summary.outcomes],
        }
