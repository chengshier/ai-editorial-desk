from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.models import (
    AIInvocationAttemptRecord,
    AIInvocationRecord,
    ConnectorDefinition,
    ConnectorInstance,
    ConnectorRun,
    ConnectorRunStatus,
    DailyCandidateRecord,
    DailyCandidateRunRecord,
    DraftClaimReferenceRecord,
    DraftSourceType,
    EditorialDecisionRecord,
    EditorialDecisionType,
    EditorialDraftRecord,
    EditorialPackRecord,
    EditorialScoreRecord,
    EditorialScoreSourceType,
    EventCardRecord,
    EventRecord,
    EventSignalRecord,
    EventTrendSnapshotRecord,
    EvidenceClaimRecord,
    EvidenceClaimSourceRecord,
    RawSignalRecord,
)
from packages.validation.domain import (
    CheckLevel,
    E2EVerificationResult,
    ValidationCheck,
    ValidationSummary,
    check,
    contains_fake_marker,
    metadata_is_synthetic,
)

_ALLOWED_BUSINESS_TASKS = frozenset(
    {"evidence_extraction", "editorial_scoring", "draft_generation", "signal_embedding"}
)


async def verify_business_invocation(
    session: AsyncSession,
    invocation_id: UUID,
    *,
    expected_provider_key: str | None = None,
) -> ValidationSummary:
    invocation = await session.get(AIInvocationRecord, invocation_id)
    if invocation is None:
        return ValidationSummary(
            (check("business_invocation", CheckLevel.BLOCK, "AI Invocation 不存在"),)
        )
    checks: list[ValidationCheck] = []
    task_ok = invocation.task_key in _ALLOWED_BUSINESS_TASKS
    checks.append(
        check(
            "business_task",
            CheckLevel.PASS if task_ok else CheckLevel.BLOCK,
            "Invocation 是正式业务 task" if task_ok else "Invocation 不是认可的业务 task",
            task_key=invocation.task_key,
        )
    )
    provider_ok = bool(
        invocation.provider_key
        and not contains_fake_marker(invocation.provider_key)
        and (
            expected_provider_key is None
            or invocation.provider_key == expected_provider_key
        )
    )
    checks.append(
        check(
            "real_provider_identity",
            CheckLevel.PASS if provider_ok else CheckLevel.BLOCK,
            "Provider identity 未命中 Fake/Mock 标记"
            if provider_ok
            else "Provider identity 不满足真实 Gate",
            provider_key=invocation.provider_key,
        )
    )
    attempts = tuple(
        (
            await session.scalars(
                select(AIInvocationAttemptRecord)
                .where(AIInvocationAttemptRecord.invocation_id == invocation.id)
                .order_by(AIInvocationAttemptRecord.attempt_no)
            )
        ).all()
    )
    attempt_ok = any(
        item.status == "succeeded"
        and not contains_fake_marker(item.provider_key)
        and (
            expected_provider_key is None
            or item.provider_key == expected_provider_key
        )
        for item in attempts
    )
    checks.append(
        check(
            "provider_attempt",
            CheckLevel.PASS if attempt_ok else CheckLevel.BLOCK,
            "存在真实 succeeded Provider Attempt"
            if attempt_ok
            else "没有可验证的真实 succeeded Provider Attempt",
            attempt_count=len(attempts),
        )
    )
    success = invocation.status == "succeeded"
    checks.append(
        check(
            "invocation_status",
            CheckLevel.PASS if success else CheckLevel.BLOCK,
            "Invocation succeeded" if success else "Invocation 未成功",
            status=invocation.status,
            usage="available" if invocation.total_tokens is not None else "unknown",
            cost="available" if invocation.estimated_cost is not None else "unknown",
        )
    )
    return ValidationSummary(tuple(checks))


async def verify_m5d_e2e(
    session: AsyncSession,
    *,
    collection_run_id: UUID,
    event_id: UUID,
    candidate_run_id: UUID,
    decision_id: UUID,
    draft_id: UUID,
) -> E2EVerificationResult:
    checks: list[ValidationCheck] = []
    evidence: dict[str, object] = {
        "collection_run_id": str(collection_run_id),
        "event_id": str(event_id),
        "candidate_run_id": str(candidate_run_id),
        "decision_id": str(decision_id),
        "draft_id": str(draft_id),
    }
    run = await session.get(ConnectorRun, collection_run_id)
    run_ok = bool(
        run
        and run.status is ConnectorRunStatus.SUCCEEDED
        and not metadata_is_synthetic(run.run_metadata)
    )
    checks.append(
        check(
            "collection_run",
            CheckLevel.PASS if run_ok else CheckLevel.BLOCK,
            "CollectionRun succeeded 且未声明 synthetic/mock/offline"
            if run_ok
            else "CollectionRun 不满足真实链路候选条件",
            status=run.status.value if run else None,
        )
    )
    if run is None:
        return E2EVerificationResult("FAIL", tuple(checks), evidence)

    instance = await session.get(ConnectorInstance, run.connector_instance_id)
    definition = None
    if instance is not None:
        definition = await session.get(ConnectorDefinition, instance.definition_id)
    connector_ok = bool(definition and definition.connector_type == "mediacrawler")
    checks.append(
        check(
            "collection_connector",
            CheckLevel.PASS if connector_ok else CheckLevel.BLOCK,
            "CollectionRun 来自 MediaCrawler 主系统链"
            if connector_ok
            else "CollectionRun 不是 MediaCrawler 主系统链",
            platform=definition.platform if definition else None,
        )
    )

    signal_ids = tuple(
        (
            await session.scalars(
                select(RawSignalRecord.id).where(
                    RawSignalRecord.connector_run_id == collection_run_id
                )
            )
        ).all()
    )
    checks.append(
        check(
            "raw_signal",
            CheckLevel.PASS if signal_ids else CheckLevel.BLOCK,
            "Run 产生 RawSignal" if signal_ids else "Run 没有关联 RawSignal",
            count=len(signal_ids),
        )
    )
    evidence["raw_signal_count"] = len(signal_ids)

    event = await session.get(EventRecord, event_id)
    active_event = bool(event and event.merged_into_event_id is None)
    checks.append(
        check(
            "event",
            CheckLevel.PASS if active_event else CheckLevel.BLOCK,
            "Event active 且未 merged" if active_event else "Event 不存在或已 merged",
        )
    )
    event_signal_count = 0
    if signal_ids:
        event_signal_count = int(
            await session.scalar(
                select(func.count())
                .select_from(EventSignalRecord)
                .where(
                    EventSignalRecord.event_id == event_id,
                    EventSignalRecord.signal_id.in_(signal_ids),
                )
            )
            or 0
        )
    checks.append(
        check(
            "event_signal_provenance",
            CheckLevel.PASS if event_signal_count else CheckLevel.BLOCK,
            "Event 绑定本次 Run 的 RawSignal"
            if event_signal_count
            else "Event 未绑定本次 Run 的 RawSignal",
            count=event_signal_count,
        )
    )

    claim_source_count = 0
    if signal_ids:
        claim_source_count = int(
            await session.scalar(
                select(func.count())
                .select_from(EvidenceClaimSourceRecord)
                .join(
                    EvidenceClaimRecord,
                    EvidenceClaimRecord.id == EvidenceClaimSourceRecord.claim_id,
                )
                .where(
                    EvidenceClaimRecord.event_id == event_id,
                    EvidenceClaimSourceRecord.signal_id.in_(signal_ids),
                )
            )
            or 0
        )
    checks.append(
        check(
            "evidence_chain",
            CheckLevel.PASS if claim_source_count else CheckLevel.BLOCK,
            "Claim 可追溯到本次 Run RawSignal"
            if claim_source_count
            else "缺少 RawSignal → Evidence Claim provenance",
            count=claim_source_count,
        )
    )
    evidence["evidence_claim_source_count"] = claim_source_count

    trend = await session.scalar(
        select(EventTrendSnapshotRecord)
        .where(EventTrendSnapshotRecord.event_id == event_id)
        .order_by(EventTrendSnapshotRecord.created_at.desc())
        .limit(1)
    )
    checks.append(
        check(
            "trend",
            CheckLevel.PASS if trend else CheckLevel.BLOCK,
            "Trend Snapshot 存在" if trend else "Trend Snapshot 缺失",
        )
    )
    evidence["trend_snapshot_id"] = str(trend.id) if trend else None

    score = await session.scalar(
        select(EditorialScoreRecord)
        .where(
            EditorialScoreRecord.event_id == event_id,
            EditorialScoreRecord.source_type == EditorialScoreSourceType.AI,
        )
        .order_by(EditorialScoreRecord.created_at.desc())
        .limit(1)
    )
    score_validation = await _artifact_invocation(session, score)
    checks.append(
        check(
            "editorial_score",
            score_validation.result,
            "可验证真实 Provider AI Score"
            if score_validation.result is not CheckLevel.BLOCK
            else "缺少可验证真实 Provider AI Score",
            score_id=str(score.id) if score else None,
        )
    )
    checks.extend(score_validation.checks)
    evidence["editorial_score_id"] = str(score.id) if score else None
    evidence["score_invocation_id"] = (
        str(score.ai_invocation_id) if score and score.ai_invocation_id else None
    )

    candidate_run = await session.get(DailyCandidateRunRecord, candidate_run_id)
    candidate = await session.scalar(
        select(DailyCandidateRecord).where(
            DailyCandidateRecord.run_id == candidate_run_id,
            DailyCandidateRecord.event_id == event_id,
        )
    )
    candidate_ok = bool(candidate_run and candidate)
    checks.append(
        check(
            "candidate",
            CheckLevel.PASS if candidate_ok else CheckLevel.BLOCK,
            "Candidate provenance 一致" if candidate_ok else "Candidate provenance 不一致",
            rank=candidate.rank if candidate else None,
            ranking_version=(candidate_run.ranking_version if candidate_run else None),
        )
    )
    evidence["algorithmic_rank"] = candidate.rank if candidate else None

    decision = await session.get(EditorialDecisionRecord, decision_id)
    decision_ok = bool(
        decision
        and candidate
        and decision.event_id == event_id
        and decision.candidate_id == candidate.id
        and decision.decision is EditorialDecisionType.ADOPT
        and decision.actor.strip()
        and decision.reason.strip()
    )
    checks.append(
        check(
            "human_decision",
            CheckLevel.PASS if decision_ok else CheckLevel.BLOCK,
            "Human Adopt 与 Candidate/Event 一致"
            if decision_ok
            else "Decision 不是指定 Candidate 的 Human Adopt",
            actor_present=bool(decision and decision.actor.strip()),
            reason_present=bool(decision and decision.reason.strip()),
        )
    )

    card = await _latest_card(session, event_id)
    pack = await _latest_pack(session, event_id)
    card_pack_ok = bool(card and pack and pack.event_card_id == card.id)
    checks.append(
        check(
            "card_pack",
            CheckLevel.PASS if card_pack_ok else CheckLevel.BLOCK,
            "Card / Pack provenance 一致" if card_pack_ok else "Card / Pack 缺失或不一致",
        )
    )
    evidence["card_id"] = str(card.id) if card else None
    evidence["pack_id"] = str(pack.id) if pack else None

    draft = await session.get(EditorialDraftRecord, draft_id)
    draft_ok = bool(
        draft
        and card
        and pack
        and draft.event_id == event_id
        and draft.source_type is DraftSourceType.AI
        and draft.event_card_id == card.id
        and draft.editorial_pack_id == pack.id
    )
    checks.append(
        check(
            "draft",
            CheckLevel.PASS if draft_ok else CheckLevel.BLOCK,
            "AI Draft provenance 一致" if draft_ok else "Draft provenance 不一致",
            version=draft.draft_version if draft else None,
        )
    )
    refs_ok = await _draft_refs_ok(session, draft, event_id)
    checks.append(
        check(
            "draft_claim_refs",
            CheckLevel.PASS if refs_ok else CheckLevel.BLOCK,
            "Draft Claim refs 属于同一 Event"
            if refs_ok
            else "Draft Claim refs 缺失或跨 Event",
        )
    )
    draft_validation = await _artifact_invocation(session, draft)
    checks.extend(draft_validation.checks)
    evidence["draft_invocation_id"] = (
        str(draft.ai_invocation_id) if draft and draft.ai_invocation_id else None
    )

    failed = any(item.level is CheckLevel.BLOCK for item in checks)
    return E2EVerificationResult("FAIL" if failed else "PASS", tuple(checks), evidence)


async def _latest_card(
    session: AsyncSession,
    event_id: UUID,
) -> EventCardRecord | None:
    return await session.scalar(
        select(EventCardRecord)
        .where(EventCardRecord.event_id == event_id)
        .order_by(EventCardRecord.created_at.desc())
        .limit(1)
    )


async def _latest_pack(
    session: AsyncSession,
    event_id: UUID,
) -> EditorialPackRecord | None:
    return await session.scalar(
        select(EditorialPackRecord)
        .where(EditorialPackRecord.event_id == event_id)
        .order_by(EditorialPackRecord.created_at.desc())
        .limit(1)
    )


async def _artifact_invocation(
    session: AsyncSession,
    artifact: EditorialScoreRecord | EditorialDraftRecord | None,
) -> ValidationSummary:
    invocation_id = artifact.ai_invocation_id if artifact else None
    if invocation_id is None:
        return ValidationSummary(
            (check("artifact_invocation", CheckLevel.BLOCK, "Artifact 缺少 AI Invocation"),)
        )
    return await verify_business_invocation(session, invocation_id)


async def _draft_refs_ok(
    session: AsyncSession,
    draft: EditorialDraftRecord | None,
    event_id: UUID,
) -> bool:
    if draft is None:
        return False
    refs = tuple(
        (
            await session.scalars(
                select(DraftClaimReferenceRecord).where(
                    DraftClaimReferenceRecord.draft_id == draft.id
                )
            )
        ).all()
    )
    if not refs:
        return False
    claim_ids = [item.claim_id for item in refs]
    valid = int(
        await session.scalar(
            select(func.count())
            .select_from(EvidenceClaimRecord)
            .where(
                EvidenceClaimRecord.id.in_(claim_ids),
                EvidenceClaimRecord.event_id == event_id,
            )
        )
        or 0
    )
    return valid == len(set(claim_ids))
