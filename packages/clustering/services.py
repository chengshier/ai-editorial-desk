from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from packages.clustering.fingerprints import (
    FingerprintInputBuilder,
    SignalFingerprint,
    hamming_distance,
)
from packages.clustering.policy import ClusterPolicy, DEFAULT_CLUSTER_POLICY
from packages.clustering.repositories import (
    ClusteringQueryRepository,
    FingerprintRepository,
    MatchDecisionRepository,
    MatchOverrideRepository,
    SignalEventSuppressionRepository,
)
from packages.connector_management.exceptions import (
    BusinessValidationError,
    ResourceNotFoundError,
)
from packages.connector_management.repositories import AuditLogRepository
from packages.database.models import (
    EventRecord,
    EventSignalAttachedBy,
    EventSignalRecord,
    EventSignalRelation,
    EventStatus,
    MatchDecisionType,
    MatchOverrideDecision,
    MatchPrimaryMethod,
    RawSignalRecord,
    SignalMatchOverrideRecord,
)
from packages.database.types import utc_now
from packages.embeddings.services import SignalSimilarityService
from packages.events.repositories import EventRepository, EventSignalRepository
from packages.signals.repositories import RawSignalRepository

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _CandidateEvidence:
    signal: RawSignalRecord
    exact_method: MatchPrimaryMethod | None = None
    simhash_distance: int | None = None
    embedding_similarity: float | None = None


@dataclass(frozen=True, slots=True)
class MatchDecision:
    candidate_signal_id: UUID
    decision: MatchDecisionType
    primary_method: MatchPrimaryMethod
    score: float
    components: dict[str, object]
    algorithm_version: str


@dataclass(frozen=True, slots=True)
class MatchPreview:
    signal_id: UUID
    fingerprint: SignalFingerprint | None
    decisions: tuple[MatchDecision, ...]


class ClusterOutcomeStatus(StrEnum):
    ATTACHED = "attached"
    CREATED_EVENT = "created_event"
    AMBIGUOUS = "ambiguous"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ClusterOutcome:
    signal_id: UUID
    status: ClusterOutcomeStatus
    code: str
    event_id: UUID | None = None
    candidate_event_ids: tuple[UUID, ...] = ()


@dataclass(frozen=True, slots=True)
class ClusterBatchSummary:
    requested: int
    processed: int
    attached: int
    created_event: int
    ambiguous: int
    skipped: int
    failed: int
    outcomes: tuple[ClusterOutcome, ...]


def _effective_time(signal: RawSignalRecord) -> datetime:
    return signal.published_at or signal.collected_at


def _semantic_text_present(signal: RawSignalRecord) -> bool:
    return bool((signal.title or "").strip() or (signal.text or "").strip())


def _normalized_title(signal: RawSignalRecord) -> str | None:
    title = " ".join((signal.title or "").split())
    if title:
        return title[:500]
    body = " ".join((signal.text or "").split())
    if not body:
        return None
    return body[:160]


def _exact_method(
    target: RawSignalRecord, candidate: RawSignalRecord
) -> MatchPrimaryMethod | None:
    if (
        target.external_id
        and candidate.external_id
        and target.platform == candidate.platform
        and target.external_id.strip() == candidate.external_id.strip()
    ):
        return MatchPrimaryMethod.EXTERNAL_ID
    if (
        target.canonical_url.strip()
        and target.canonical_url == candidate.canonical_url
    ):
        return MatchPrimaryMethod.CANONICAL_URL
    if (
        _semantic_text_present(target)
        and _semantic_text_present(candidate)
        and target.content_hash == candidate.content_hash
    ):
        return MatchPrimaryMethod.CONTENT_HASH
    return None


def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, value))


class SignalMatchService:
    """Side-effect-free matching preview over exact, SimHash and M3-B recall evidence."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        policy: ClusterPolicy = DEFAULT_CLUSTER_POLICY,
        fingerprint_builder: FingerprintInputBuilder | None = None,
    ) -> None:
        self.session = session
        self.policy = policy
        self.fingerprint_builder = fingerprint_builder or FingerprintInputBuilder()
        self.raw_signals = RawSignalRepository(session)
        self.queries = ClusteringQueryRepository(session)
        self.overrides = MatchOverrideRepository(session)

    async def preview(
        self,
        *,
        signal_id: UUID,
        embedding_version: str | None = None,
    ) -> MatchPreview:
        async with self.session.begin():
            target = await self.raw_signals.get(signal_id)
            if target is None:
                raise ResourceNotFoundError("原始信号不存在")
            target_fingerprint = self.fingerprint_builder.fingerprint(target)
            evidence = await self._collect_candidates(
                target=target,
                target_fingerprint=target_fingerprint,
                embedding_version=embedding_version,
            )
            decisions = [
                await self._decide_pair(
                    target=target,
                    target_fingerprint=target_fingerprint,
                    evidence=item,
                )
                for item in evidence
            ]
        decisions.sort(
            key=lambda item: (
                -item.score,
                item.candidate_signal_id.int,
            )
        )
        return MatchPreview(
            signal_id=signal_id,
            fingerprint=target_fingerprint,
            decisions=tuple(decisions[: self.policy.max_candidates]),
        )

    async def _collect_candidates(
        self,
        *,
        target: RawSignalRecord,
        target_fingerprint: SignalFingerprint | None,
        embedding_version: str | None,
    ) -> list[_CandidateEvidence]:
        candidates: dict[UUID, _CandidateEvidence] = {}
        exact = await self.queries.exact_candidates(target, limit=self.policy.max_candidates)
        for candidate in exact:
            candidates[candidate.id] = _CandidateEvidence(
                signal=candidate,
                exact_method=_exact_method(target, candidate),
            )

        if target_fingerprint is not None:
            bounded = await self.queries.bounded_time_candidates(
                target=target,
                max_time_gap=self.policy.max_time_gap,
                limit=self.policy.max_fingerprint_scan,
            )
            for candidate in bounded:
                candidate_fingerprint = self.fingerprint_builder.fingerprint(candidate)
                if candidate_fingerprint is None:
                    continue
                distance = hamming_distance(
                    target_fingerprint.simhash, candidate_fingerprint.simhash
                )
                if distance > self.policy.simhash_candidate_max_distance:
                    continue
                item = candidates.setdefault(
                    candidate.id, _CandidateEvidence(signal=candidate)
                )
                item.simhash_distance = distance
                if item.exact_method is None:
                    item.exact_method = _exact_method(target, candidate)

        if embedding_version is not None:
            target_time = _effective_time(target)
            try:
                recalled = await SignalSimilarityService(self.session).recall(
                    signal_id=target.id,
                    embedding_version=embedding_version,
                    top_k=self.policy.max_candidates,
                    time_from=target_time - self.policy.max_time_gap,
                    time_to=target_time + self.policy.max_time_gap,
                )
            except ResourceNotFoundError:
                recalled = []
            for recalled_item in recalled:
                candidate = await self.raw_signals.get(recalled_item.candidate_signal_id)
                if candidate is None:
                    continue
                item = candidates.setdefault(
                    candidate.id, _CandidateEvidence(signal=candidate)
                )
                item.embedding_similarity = recalled_item.similarity
                if item.exact_method is None:
                    item.exact_method = _exact_method(target, candidate)
                if target_fingerprint is not None and item.simhash_distance is None:
                    candidate_fingerprint = self.fingerprint_builder.fingerprint(candidate)
                    if candidate_fingerprint is not None:
                        item.simhash_distance = hamming_distance(
                            target_fingerprint.simhash, candidate_fingerprint.simhash
                        )

        ranked = list(candidates.values())
        ranked.sort(
            key=lambda item: (
                0 if item.exact_method is not None else 1,
                item.simhash_distance if item.simhash_distance is not None else 65,
                -(item.embedding_similarity if item.embedding_similarity is not None else -1.0),
                item.signal.id.int,
            )
        )
        return ranked[: self.policy.max_candidates]

    async def _decide_pair(
        self,
        *,
        target: RawSignalRecord,
        target_fingerprint: SignalFingerprint | None,
        evidence: _CandidateEvidence,
    ) -> MatchDecision:
        candidate = evidence.signal
        override = await self.overrides.get(target.id, candidate.id)
        if override is not None:
            return self._decision_from_override(candidate.id, override)

        time_gap_seconds = abs(
            (_effective_time(target) - _effective_time(candidate)).total_seconds()
        )
        components: dict[str, object] = {
            "canonical_url_match": bool(
                target.canonical_url.strip()
                and target.canonical_url == candidate.canonical_url
            ),
            "content_hash_match": bool(
                _semantic_text_present(target)
                and _semantic_text_present(candidate)
                and target.content_hash == candidate.content_hash
            ),
            "external_id_match": bool(
                target.external_id
                and candidate.external_id
                and target.platform == candidate.platform
                and target.external_id.strip() == candidate.external_id.strip()
            ),
            "simhash_distance": evidence.simhash_distance,
            "embedding_similarity": evidence.embedding_similarity,
            "time_gap_seconds": time_gap_seconds,
            "same_platform": target.platform == candidate.platform,
            "same_source": target.source_id == candidate.source_id,
            "fingerprint_version": (
                target_fingerprint.fingerprint_version if target_fingerprint else None
            ),
        }

        if evidence.exact_method is not None:
            return MatchDecision(
                candidate_signal_id=candidate.id,
                decision=MatchDecisionType.EXACT_DUPLICATE,
                primary_method=evidence.exact_method,
                score=1.0,
                components=components,
                algorithm_version=self.policy.algorithm_version,
            )

        if (
            evidence.simhash_distance is not None
            and evidence.simhash_distance <= self.policy.simhash_duplicate_max_distance
        ):
            score = min(
                1.0,
                0.96
                + 0.01
                * (self.policy.simhash_duplicate_max_distance - evidence.simhash_distance),
            )
            return MatchDecision(
                candidate_signal_id=candidate.id,
                decision=MatchDecisionType.NEAR_DUPLICATE,
                primary_method=MatchPrimaryMethod.SIMHASH,
                score=score,
                components=components,
                algorithm_version=self.policy.algorithm_version,
            )

        simhash_component = 0.0
        if evidence.simhash_distance is not None:
            simhash_component = _clamp(
                1.0
                - evidence.simhash_distance
                / self.policy.simhash_candidate_max_distance
            )
        time_component = _clamp(
            1.0 - time_gap_seconds / self.policy.max_time_gap.total_seconds()
        )
        if evidence.embedding_similarity is not None:
            embedding_component = _clamp(
                (evidence.embedding_similarity + 1.0) / 2.0
            )
            score = (
                0.75 * embedding_component
                + 0.15 * simhash_component
                + 0.10 * time_component
            )
            primary_method = MatchPrimaryMethod.COMBINED
        else:
            embedding_component = None
            score = 0.70 * simhash_component + 0.30 * time_component
            primary_method = MatchPrimaryMethod.SIMHASH
        score = _clamp(score)
        components["embedding_component"] = embedding_component
        components["simhash_component"] = simhash_component
        components["time_component"] = time_component
        components["combined_score"] = score

        if time_gap_seconds > self.policy.max_time_gap.total_seconds():
            if (
                evidence.embedding_similarity is not None
                and evidence.embedding_similarity >= self.policy.embedding_same_event_threshold
            ) or simhash_component > 0:
                decision = MatchDecisionType.AMBIGUOUS
            else:
                decision = MatchDecisionType.DISTINCT
        else:
            high_boundary = (
                self.policy.same_event_score_threshold + self.policy.ambiguous_margin
            )
            distinct_boundary = max(
                0.0,
                self.policy.distinct_score_threshold - self.policy.ambiguous_margin,
            )
            if (
                evidence.embedding_similarity is not None
                and evidence.embedding_similarity >= self.policy.embedding_same_event_threshold
                and score >= high_boundary
            ):
                decision = MatchDecisionType.SAME_EVENT
            elif (
                evidence.embedding_similarity is not None
                and evidence.embedding_similarity <= self.policy.embedding_distinct_threshold
                and simhash_component == 0
            ) or score <= distinct_boundary:
                decision = MatchDecisionType.DISTINCT
            else:
                decision = MatchDecisionType.AMBIGUOUS

        return MatchDecision(
            candidate_signal_id=candidate.id,
            decision=decision,
            primary_method=primary_method,
            score=score,
            components=components,
            algorithm_version=self.policy.algorithm_version,
        )

    def _decision_from_override(
        self,
        candidate_signal_id: UUID,
        override: SignalMatchOverrideRecord,
    ) -> MatchDecision:
        decision = (
            MatchDecisionType.SAME_EVENT
            if override.decision is MatchOverrideDecision.SAME_EVENT
            else MatchDecisionType.DISTINCT
        )
        return MatchDecision(
            candidate_signal_id=candidate_signal_id,
            decision=decision,
            primary_method=MatchPrimaryMethod.HUMAN,
            score=1.0 if decision is MatchDecisionType.SAME_EVENT else 0.0,
            components={
                "human_override": True,
                "override_reason": override.reason,
                "override_actor": override.actor,
            },
            algorithm_version=self.policy.algorithm_version,
        )


class EventClusteringService:
    """Conservatively assign one RawSignal to an Event using persisted evidence."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        policy: ClusterPolicy = DEFAULT_CLUSTER_POLICY,
    ) -> None:
        self.session = session
        self.policy = policy
        self.matcher = SignalMatchService(session, policy=policy)
        self.fingerprints = FingerprintRepository(session)
        self.decisions = MatchDecisionRepository(session)
        self.overrides = MatchOverrideRepository(session)
        self.suppressions = SignalEventSuppressionRepository(session)
        self.queries = ClusteringQueryRepository(session)
        self.events = EventRepository(session)
        self.event_signals = EventSignalRepository(session)
        self.raw_signals = RawSignalRepository(session)
        self.audit = AuditLogRepository(session)

    async def cluster_signal(
        self,
        *,
        signal_id: UUID,
        embedding_version: str | None,
        actor: str,
    ) -> ClusterOutcome:
        preview = await self.matcher.preview(
            signal_id=signal_id,
            embedding_version=embedding_version,
        )
        async with self.session.begin():
            target = await self.queries.get_signal_for_update(signal_id)
            if target is None:
                raise ResourceNotFoundError("原始信号不存在")

            human_memberships = await self.queries.human_active_memberships(signal_id)
            if human_memberships:
                return ClusterOutcome(
                    signal_id=signal_id,
                    status=ClusterOutcomeStatus.SKIPPED,
                    code="HUMAN_MEMBERSHIP_PRESERVED",
                    event_id=human_memberships[0].event_id,
                )
            memberships = await self.queries.active_memberships(signal_id)
            if memberships:
                return ClusterOutcome(
                    signal_id=signal_id,
                    status=ClusterOutcomeStatus.SKIPPED,
                    code="ALREADY_ASSIGNED",
                    event_id=memberships[0].event_id,
                )

            await self._persist_fingerprint(preview.fingerprint)
            decisions = await self._refresh_human_overrides(signal_id, preview.decisions)
            await self._persist_automatic_decisions(signal_id, decisions)
            return await self._assign(
                target=target,
                decisions=decisions,
                actor=actor,
            )

    async def _persist_fingerprint(self, fingerprint: SignalFingerprint | None) -> None:
        if fingerprint is None:
            return
        record, _created = await self.fingerprints.insert_idempotently(
            signal_id=fingerprint.signal_id,
            fingerprint_version=fingerprint.fingerprint_version,
            input_hash=fingerprint.input_hash,
            simhash=fingerprint.simhash,
            token_count=fingerprint.token_count,
        )
        if (
            record.input_hash != fingerprint.input_hash
            or record.simhash != fingerprint.simhash
            or record.token_count != fingerprint.token_count
        ):
            raise BusinessValidationError(
                "FINGERPRINT_VERSION_CONFLICT：输入或算法变化时必须升级 fingerprint_version"
            )

    async def _refresh_human_overrides(
        self,
        signal_id: UUID,
        decisions: tuple[MatchDecision, ...],
    ) -> tuple[MatchDecision, ...]:
        refreshed: list[MatchDecision] = []
        for decision in decisions:
            override = await self.overrides.get(signal_id, decision.candidate_signal_id)
            if override is None:
                refreshed.append(decision)
            else:
                refreshed.append(
                    self.matcher._decision_from_override(  # noqa: SLF001
                        decision.candidate_signal_id, override
                    )
                )
        return tuple(refreshed)

    async def _persist_automatic_decisions(
        self,
        signal_id: UUID,
        decisions: tuple[MatchDecision, ...],
    ) -> None:
        for decision in decisions:
            if decision.primary_method is MatchPrimaryMethod.HUMAN:
                continue
            await self.decisions.insert_idempotently(
                left_signal_id=signal_id,
                right_signal_id=decision.candidate_signal_id,
                decision=decision.decision,
                primary_method=decision.primary_method,
                score=decision.score,
                components=decision.components,
                algorithm_version=decision.algorithm_version,
            )

    async def _assign(
        self,
        *,
        target: RawSignalRecord,
        decisions: tuple[MatchDecision, ...],
        actor: str,
    ) -> ClusterOutcome:
        positive = {
            MatchDecisionType.EXACT_DUPLICATE,
            MatchDecisionType.NEAR_DUPLICATE,
            MatchDecisionType.SAME_EVENT,
        }
        positive_decisions = [item for item in decisions if item.decision in positive]
        ambiguous_present = any(
            item.decision is MatchDecisionType.AMBIGUOUS for item in decisions
        )

        candidate_events: dict[UUID, list[MatchDecision]] = {}
        for decision in positive_decisions:
            memberships = await self.queries.active_memberships(decision.candidate_signal_id)
            if len(memberships) > 1:
                return ClusterOutcome(
                    signal_id=target.id,
                    status=ClusterOutcomeStatus.AMBIGUOUS,
                    code="CANDIDATE_SIGNAL_HAS_MULTIPLE_EVENTS",
                    candidate_event_ids=tuple(
                        sorted(
                            {item.event_id for item in memberships},
                            key=lambda value: value.int,
                        )
                    ),
                )
            if len(memberships) == 1:
                candidate_events.setdefault(memberships[0].event_id, []).append(decision)

        if len(candidate_events) > 1:
            return ClusterOutcome(
                signal_id=target.id,
                status=ClusterOutcomeStatus.AMBIGUOUS,
                code="MULTIPLE_CANDIDATE_EVENTS",
                candidate_event_ids=tuple(
                    sorted(candidate_events, key=lambda value: value.int)
                ),
            )
        if len(candidate_events) == 1:
            event_id = next(iter(candidate_events))
            if await self.suppressions.is_active(target.id, event_id):
                return ClusterOutcome(
                    signal_id=target.id,
                    status=ClusterOutcomeStatus.AMBIGUOUS,
                    code="HUMAN_EVENT_SUPPRESSION",
                    candidate_event_ids=(event_id,),
                )
            best = max(
                candidate_events[event_id],
                key=lambda item: (item.score, -item.candidate_signal_id.int),
            )
            return await self._attach_to_event(
                target=target,
                event_id=event_id,
                decision=best,
                actor=actor,
            )

        if ambiguous_present:
            return ClusterOutcome(
                signal_id=target.id,
                status=ClusterOutcomeStatus.AMBIGUOUS,
                code="AMBIGUOUS_MATCH_REQUIRES_REVIEW",
            )
        return await self._create_event(target=target, actor=actor)

    async def _attach_to_event(
        self,
        *,
        target: RawSignalRecord,
        event_id: UUID,
        decision: MatchDecision,
        actor: str,
    ) -> ClusterOutcome:
        event = await self.events.get_for_update(event_id)
        if event is None or event.merged_into_event_id is not None:
            return ClusterOutcome(
                signal_id=target.id,
                status=ClusterOutcomeStatus.AMBIGUOUS,
                code="CANDIDATE_EVENT_NOT_ACTIVE",
            )
        attached_by = (
            EventSignalAttachedBy.HUMAN
            if decision.primary_method is MatchPrimaryMethod.HUMAN
            else EventSignalAttachedBy.RULE
            if decision.decision
            in {MatchDecisionType.EXACT_DUPLICATE, MatchDecisionType.NEAR_DUPLICATE}
            else EventSignalAttachedBy.EMBEDDING
        )
        association, created = await self.event_signals.attach(
            event_id=event.id,
            signal_id=target.id,
            relation=EventSignalRelation.RELATED,
            confidence=decision.score,
            attached_by=attached_by,
        )
        if not created:
            return ClusterOutcome(
                signal_id=target.id,
                status=ClusterOutcomeStatus.SKIPPED,
                code="CONCURRENTLY_ASSIGNED",
                event_id=association.event_id,
            )
        await self._recalculate_event(event)
        event.last_updated_at = utc_now()
        self.audit.add(
            entity_type="event",
            entity_id=event.id,
            action="cluster_attach_signal",
            actor=actor,
            before_data={},
            after_data={
                "signal_id": str(target.id),
                "relation": EventSignalRelation.RELATED.value,
                "attached_by": attached_by.value,
                "algorithm_version": self.policy.algorithm_version,
                "match_decision": decision.decision.value,
                "match_score": decision.score,
            },
        )
        return ClusterOutcome(
            signal_id=target.id,
            status=ClusterOutcomeStatus.ATTACHED,
            code="ATTACHED_TO_EXISTING_EVENT",
            event_id=event.id,
        )

    async def _create_event(
        self, *, target: RawSignalRecord, actor: str
    ) -> ClusterOutcome:
        title = _normalized_title(target)
        if title is None:
            return ClusterOutcome(
                signal_id=target.id,
                status=ClusterOutcomeStatus.SKIPPED,
                code="NO_EVENT_TITLE_TEXT",
            )
        now = utc_now()
        event = EventRecord(
            title=title,
            summary=None,
            category=None,
            status=EventStatus.EMERGING,
            first_seen_at=None,
            last_updated_at=now,
            primary_language=target.language,
            entities=[],
            keywords=[],
            source_count=0,
            platform_count=0,
        )
        self.events.add(event)
        await self.session.flush()
        await self.event_signals.attach(
            event_id=event.id,
            signal_id=target.id,
            relation=EventSignalRelation.RELATED,
            confidence=1.0,
            attached_by=EventSignalAttachedBy.RULE,
        )
        await self._recalculate_event(event)
        event.last_updated_at = now
        self.audit.add(
            entity_type="event",
            entity_id=event.id,
            action="cluster_create_event",
            actor=actor,
            before_data={},
            after_data={
                "signal_id": str(target.id),
                "relation": EventSignalRelation.RELATED.value,
                "attached_by": EventSignalAttachedBy.RULE.value,
                "algorithm_version": self.policy.algorithm_version,
            },
        )
        return ClusterOutcome(
            signal_id=target.id,
            status=ClusterOutcomeStatus.CREATED_EVENT,
            code="CREATED_NEW_EVENT",
            event_id=event.id,
        )

    async def _recalculate_event(self, event: EventRecord) -> None:
        source_count, platform_count, first_seen_at = (
            await self.event_signals.aggregate_stats(event.id)
        )
        event.source_count = source_count
        event.platform_count = platform_count
        event.first_seen_at = first_seen_at


class ClusteringBatchProcessor:
    def __init__(
        self,
        session: AsyncSession,
        *,
        policy: ClusterPolicy = DEFAULT_CLUSTER_POLICY,
    ) -> None:
        self.session = session
        self.policy = policy

    async def process(
        self,
        *,
        signal_ids: list[UUID],
        embedding_version: str | None,
        actor: str,
        batch_size: int = 25,
    ) -> ClusterBatchSummary:
        if batch_size < 1 or batch_size > self.policy.max_batch_size:
            raise BusinessValidationError(
                f"batch_size 必须在 1 到 {self.policy.max_batch_size} 之间"
            )
        unique_ids = sorted(set(signal_ids), key=lambda value: value.int)
        outcomes: list[ClusterOutcome] = []
        service = EventClusteringService(self.session, policy=self.policy)
        for offset in range(0, len(unique_ids), batch_size):
            for signal_id in unique_ids[offset : offset + batch_size]:
                try:
                    outcome = await service.cluster_signal(
                        signal_id=signal_id,
                        embedding_version=embedding_version,
                        actor=actor,
                    )
                except (BusinessValidationError, ResourceNotFoundError) as exc:
                    outcome = ClusterOutcome(
                        signal_id=signal_id,
                        status=ClusterOutcomeStatus.FAILED,
                        code=type(exc).__name__,
                    )
                outcomes.append(outcome)
        summary = ClusterBatchSummary(
            requested=len(unique_ids),
            processed=len(outcomes),
            attached=sum(item.status is ClusterOutcomeStatus.ATTACHED for item in outcomes),
            created_event=sum(
                item.status is ClusterOutcomeStatus.CREATED_EVENT for item in outcomes
            ),
            ambiguous=sum(
                item.status is ClusterOutcomeStatus.AMBIGUOUS for item in outcomes
            ),
            skipped=sum(item.status is ClusterOutcomeStatus.SKIPPED for item in outcomes),
            failed=sum(item.status is ClusterOutcomeStatus.FAILED for item in outcomes),
            outcomes=tuple(outcomes),
        )
        logger.info(
            "clustering_batch_complete",
            extra={
                "matching_algorithm_version": self.policy.algorithm_version,
                "fingerprint_version": self.policy.fingerprint_version,
                "clustering_batch_size": batch_size,
                "clustering_requested": summary.requested,
                "clustering_processed": summary.processed,
                "clustering_attached": summary.attached,
                "clustering_created_event": summary.created_event,
                "clustering_ambiguous": summary.ambiguous,
                "clustering_skipped": summary.skipped,
                "clustering_failed": summary.failed,
            },
        )
        return summary


class EventClusterMaintenanceService:
    """Human merge/split operations with durable anti-reversal state."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        policy: ClusterPolicy = DEFAULT_CLUSTER_POLICY,
    ) -> None:
        self.session = session
        self.policy = policy
        self.events = EventRepository(session)
        self.event_signals = EventSignalRepository(session)
        self.queries = ClusteringQueryRepository(session)
        self.overrides = MatchOverrideRepository(session)
        self.suppressions = SignalEventSuppressionRepository(session)
        self.raw_signals = RawSignalRepository(session)
        self.audit = AuditLogRepository(session)

    async def merge(
        self,
        *,
        target_event_id: UUID,
        source_event_id: UUID,
        reason: str,
        actor: str,
    ) -> EventRecord:
        if target_event_id == source_event_id:
            raise BusinessValidationError("Event 不能 merge 到自身")
        normalized_reason = reason.strip()
        if not normalized_reason:
            raise BusinessValidationError("merge reason 不能为空")

        async with self.session.begin():
            locked = await self.queries.lock_events([target_event_id, source_event_id])
            locked_by_id = {event.id: event for event in locked}
            target = locked_by_id.get(target_event_id)
            source = locked_by_id.get(source_event_id)
            if target is None or source is None:
                raise ResourceNotFoundError("merge Event 不存在")
            if target.merged_into_event_id is not None:
                raise BusinessValidationError("merge target 必须是 active Event")
            if source.merged_into_event_id is not None:
                raise BusinessValidationError("merge source 已经被合并")

            target_signals = await self.event_signals.list_all(target.id)
            source_signals = await self.event_signals.list_all(source.id)
            target_by_signal = {item.signal_id: item for item in target_signals}
            source_signal_ids = [item.signal_id for item in source_signals]
            target_signal_ids = [item.signal_id for item in target_signals]

            for source_association in source_signals:
                target_association = target_by_signal.get(source_association.signal_id)
                if target_association is None:
                    source_association.event_id = target.id
                    target_by_signal[source_association.signal_id] = source_association
                    continue
                if (
                    target_association.attached_by is not EventSignalAttachedBy.HUMAN
                    and (
                        source_association.attached_by is EventSignalAttachedBy.HUMAN
                        or source_association.confidence > target_association.confidence
                    )
                ):
                    target_association.relation = source_association.relation
                    target_association.confidence = source_association.confidence
                    target_association.attached_by = source_association.attached_by
                await self.event_signals.delete(source_association)

            await self.session.flush()
            await self._supersede_cross_distinct_overrides(
                left_ids=source_signal_ids,
                right_ids=target_signal_ids,
                reason=normalized_reason,
                actor=actor,
            )
            for signal_id in source_signal_ids:
                await self.suppressions.deactivate(signal_id, target.id)
            await self.suppressions.deactivate_for_event(source.id)

            await self._recalculate_event(target)
            await self._recalculate_event(source)
            now = utc_now()
            target.last_updated_at = now
            source.last_updated_at = now
            source.merged_into_event_id = target.id
            await self.session.execute(
                update(EventRecord)
                .where(EventRecord.merged_into_event_id == source.id)
                .values(merged_into_event_id=target.id, updated_at=func.now())
            )
            await self.session.flush()
            self.audit.add(
                entity_type="event",
                entity_id=target.id,
                action="merge_event",
                actor=actor,
                before_data={"source_event_id": str(source.id)},
                after_data={
                    "target_event_id": str(target.id),
                    "source_event_id": str(source.id),
                    "reason": normalized_reason,
                    "source_retained": True,
                },
            )
            return target

    async def split(
        self,
        *,
        event_id: UUID,
        signal_ids: list[UUID],
        title: str | None,
        reason: str,
        actor: str,
    ) -> EventRecord:
        normalized_reason = reason.strip()
        if not normalized_reason:
            raise BusinessValidationError("split reason 不能为空")
        requested_ids = sorted(set(signal_ids), key=lambda value: value.int)
        if not requested_ids:
            raise BusinessValidationError("split 至少选择一个 Signal")

        async with self.session.begin():
            source = await self.events.get_for_update(event_id)
            if source is None:
                raise ResourceNotFoundError("Event 不存在")
            if source.merged_into_event_id is not None:
                raise BusinessValidationError("已合并 Event 不能 split")
            associations = await self.event_signals.list_all(event_id)
            by_signal = {item.signal_id: item for item in associations}
            missing = [signal_id for signal_id in requested_ids if signal_id not in by_signal]
            if missing:
                raise BusinessValidationError("split 包含不属于该 Event 的 Signal")
            if len(requested_ids) >= len(associations):
                raise BusinessValidationError("split 必须至少在原 Event 保留一个 Signal")

            remaining_ids = [
                item.signal_id for item in associations if item.signal_id not in set(requested_ids)
            ]
            pair_count = len(requested_ids) * len(remaining_ids)
            if pair_count > self.policy.max_split_override_pairs:
                raise BusinessValidationError(
                    "split 跨边界 Signal pair 过多，请拆分为更小的人工操作"
                )

            new_title = " ".join((title or "").split())[:500]
            if not new_title:
                first_signal = await self.raw_signals.get(requested_ids[0])
                if first_signal is None:
                    raise ResourceNotFoundError("split Signal 不存在")
                fallback = _normalized_title(first_signal)
                if fallback is None:
                    raise BusinessValidationError("split 新 Event 缺少可用 title/text")
                new_title = fallback

            now = utc_now()
            new_event = EventRecord(
                title=new_title,
                summary=None,
                category=None,
                status=EventStatus.EMERGING,
                first_seen_at=None,
                last_updated_at=now,
                primary_language=None,
                entities=[],
                keywords=[],
                source_count=0,
                platform_count=0,
            )
            self.events.add(new_event)
            await self.session.flush()
            for signal_id in requested_ids:
                by_signal[signal_id].event_id = new_event.id
            await self.session.flush()

            for moved_id in requested_ids:
                await self.suppressions.upsert_active(
                    signal_id=moved_id,
                    event_id=source.id,
                    reason=f"manual_split:{normalized_reason}",
                    actor=actor,
                )
                for remaining_id in remaining_ids:
                    await self.overrides.upsert(
                        left_signal_id=moved_id,
                        right_signal_id=remaining_id,
                        decision=MatchOverrideDecision.DISTINCT,
                        reason=f"manual_split:{normalized_reason}",
                        actor=actor,
                    )
            for remaining_id in remaining_ids:
                await self.suppressions.upsert_active(
                    signal_id=remaining_id,
                    event_id=new_event.id,
                    reason=f"manual_split:{normalized_reason}",
                    actor=actor,
                )

            await self._recalculate_event(source)
            await self._recalculate_event(new_event)
            source.last_updated_at = now
            new_event.last_updated_at = now
            await self.session.flush()
            self.audit.add(
                entity_type="event",
                entity_id=source.id,
                action="split_event",
                actor=actor,
                before_data={"event_id": str(source.id)},
                after_data={
                    "new_event_id": str(new_event.id),
                    "moved_signal_ids": [str(value) for value in requested_ids],
                    "reason": normalized_reason,
                    "human_distinct_pairs": pair_count,
                },
            )
            return new_event

    async def _supersede_cross_distinct_overrides(
        self,
        *,
        left_ids: list[UUID],
        right_ids: list[UUID],
        reason: str,
        actor: str,
    ) -> None:
        if not left_ids or not right_ids:
            return
        from packages.database.models import SignalMatchOverrideRecord

        await self.session.execute(
            update(SignalMatchOverrideRecord)
            .where(
                SignalMatchOverrideRecord.decision == MatchOverrideDecision.DISTINCT,
                (
                    SignalMatchOverrideRecord.left_signal_id.in_(left_ids)
                    & SignalMatchOverrideRecord.right_signal_id.in_(right_ids)
                )
                | (
                    SignalMatchOverrideRecord.left_signal_id.in_(right_ids)
                    & SignalMatchOverrideRecord.right_signal_id.in_(left_ids)
                ),
            )
            .values(
                decision=MatchOverrideDecision.SAME_EVENT,
                reason=f"manual_merge:{reason}",
                actor=actor,
                updated_at=func.now(),
            )
        )

    async def _recalculate_event(self, event: EventRecord) -> None:
        source_count, platform_count, first_seen_at = (
            await self.event_signals.aggregate_stats(event.id)
        )
        event.source_count = source_count
        event.platform_count = platform_count
        event.first_seen_at = first_seen_at
