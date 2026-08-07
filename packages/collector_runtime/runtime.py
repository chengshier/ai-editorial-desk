from __future__ import annotations

from time import monotonic
from uuid import UUID

from packages.collector_runtime.budget_types import BudgetReservation
from packages.collector_runtime.budgets import CollectionBudgetService
from packages.collector_runtime.context import INGESTION_BATCH_SIZE, RuntimeResult
from packages.collector_runtime.exceptions import BudgetExceededError
from packages.collector_runtime.protocols import CollectionTask
from packages.collector_runtime.support import CollectorRuntimeSupport
from packages.connector_management.exceptions import VersionConflictError
from packages.connector_management.services import ConnectorRunService
from packages.connectors import CollectRequest
from packages.connectors.base import CollectionItemError, CollectionRiskSignal
from packages.connectors.http import ConnectorFetchError
from packages.database.models import ConnectorRunStatus
from packages.risk_guard.classifier import classify_platform_error
from packages.risk_guard.models import PlatformRiskError, RiskEvent
from packages.signals.comment_service import RawSignalCommentService
from packages.signals.domain import NormalizedSignal
from packages.signals.services import RawSignalService, SourceService
from packages.signals.urls import normalize_http_url


class CollectorRuntime(CollectorRuntimeSupport):
    """Execute one bounded task without holding a transaction over network I/O."""

    async def execute(self, task: CollectionTask) -> RuntimeResult:
        started = monotonic()
        context = await self.preflight(task)
        checkpoint = await self.load_checkpoint(task, context)
        run = await self.create_run(task, context, checkpoint)
        reservations: tuple[BudgetReservation, ...] = ()
        claimed = False
        signal_ids: list[UUID] = []
        collected_count = 0
        inserted_count = 0
        duplicate_count = 0
        actual_comments = 0

        try:
            requested_comments = self.requested_comment_budget(
                context.source.config,
                task.mode,
                task.requested_limit,
            )
            async with self.session_factory() as session:
                reservations = await CollectionBudgetService(session).reserve(
                    platform=context.definition.platform,
                    connector_instance_id=context.instance.id,
                    connector_type=context.definition.connector_type,
                    platform_account_id=task.platform_account_id,
                    source_id=context.source.id,
                    requested_items=task.requested_limit,
                    requested_comments=requested_comments,
                    actor=task.triggered_by,
                )
            budget_metadata = self.budget_metadata(reservations)
            async with self.session_factory() as session:
                await ConnectorRunService(session).claim(run_id=run.id)
            claimed = True

            connector = self.registry.create(context.definition.connector_type)
            collection = await connector.collect(
                CollectRequest(
                    source_id=str(context.source.id),
                    mode=task.mode,
                    query=context.source.external_ref,
                    limit=task.requested_limit,
                    account_id=(
                        str(task.platform_account_id)
                        if task.platform_account_id is not None
                        else None
                    ),
                    checkpoint=(
                        dict(checkpoint.checkpoint_data)
                        if checkpoint is not None
                        else None
                    ),
                    parameters=dict(context.source.config),
                    run_id=str(run.id),
                    platform=context.definition.platform,
                    account_ref=(
                        str(context.account.id)
                        if context.account is not None
                        else None
                    ),
                    browser_profile_ref=(
                        context.account.browser_profile_ref
                        if context.account is not None
                        else None
                    ),
                    runtime_context=context.runtime_context,
                )
            )

            normalized = [
                NormalizedSignal.from_connector_signal(
                    source_id=context.source.id,
                    connector_instance_id=context.instance.id,
                    connector_run_id=run.id,
                    connector_type=context.definition.connector_type,
                    signal=signal,
                    canonical_url=normalize_http_url(
                        signal.canonical_url or signal.url
                    ),
                )
                for signal in collection.signals
            ]
            collected_count = len(collection.signals)
            runtime_errors = list(collection.errors)
            signal_by_external_id: dict[str, UUID] = {}
            comment_inserted_count = 0
            comment_duplicate_count = 0
            reported_comment_count = self.reported_comment_count(
                collection.metadata
            )
            reported_comment_count += len(collection.comments)
            comment_candidates = collection.comments
            if reported_comment_count > requested_comments:
                runtime_errors.append(
                    CollectionItemError(
                        code="comment_result_exceeds_budget",
                        message="评论结果超过本次已预留评论预算，超出部分未入库",
                    )
                )
                comment_candidates = collection.comments[:requested_comments]
            actual_comments = min(reported_comment_count, requested_comments)

            if not task.dry_run:
                for offset in range(0, len(normalized), INGESTION_BATCH_SIZE):
                    batch = normalized[offset : offset + INGESTION_BATCH_SIZE]
                    async with self.session_factory() as session:
                        results = await RawSignalService(session).ingest_many(batch)
                    signal_ids.extend(item.signal_id for item in results)
                    inserted_count += sum(1 for item in results if item.created)
                    duplicate_count += sum(
                        1 for item in results if item.duplicate
                    )
                    for signal, result in zip(batch, results, strict=True):
                        if signal.external_id:
                            signal_by_external_id[signal.external_id] = (
                                result.signal_id
                            )

                for comment in comment_candidates:
                    raw_signal_id = signal_by_external_id.get(
                        comment.content_external_id
                    )
                    if raw_signal_id is None:
                        runtime_errors.append(
                            CollectionItemError(
                                code="comment_parent_signal_missing",
                                message="评论对应主内容未在本次结果中成功入库",
                                external_ref=comment.external_comment_id,
                            )
                        )
                        continue
                    try:
                        async with self.session_factory() as session:
                            comment_result = await RawSignalCommentService(
                                session
                            ).ingest(
                                raw_signal_id=raw_signal_id,
                                comment=comment,
                            )
                        comment_inserted_count += int(comment_result.created)
                        comment_duplicate_count += int(comment_result.duplicate)
                    except Exception:
                        runtime_errors.append(
                            CollectionItemError(
                                code="comment_ingestion_failed",
                                message="单条评论持久化失败",
                                external_ref=comment.external_comment_id,
                            )
                        )

            manual_risk = self._manual_risk(collection.risk_signals)
            checkpoint_error: VersionConflictError | None = None
            checkpoint_committed = False
            checkpoint_safe = (
                manual_risk is None
                or manual_risk.checkpoint_safe_to_commit
            )
            if (
                not task.dry_run
                and checkpoint is not None
                and collection.checkpoint is not None
                and collection.signals
                and not runtime_errors
                and checkpoint_safe
            ):
                try:
                    await self.advance_checkpoint(
                        checkpoint_id=checkpoint.id,
                        expected_version=checkpoint.version,
                        checkpoint_data=collection.checkpoint,
                        signals=collection.signals,
                    )
                    checkpoint_committed = True
                except VersionConflictError as exc:
                    checkpoint_error = exc

            metadata = {
                **collection.metadata,
                "task": task.to_dict(),
                "budget": {
                    "reservations": budget_metadata,
                    "actual_items": collected_count,
                    "actual_comments": actual_comments,
                    "completed": True,
                },
                "comments": {
                    "mapped": len(collection.comments),
                    "inserted": comment_inserted_count,
                    "duplicates": comment_duplicate_count,
                },
                "error_samples": [
                    {
                        "code": item.code,
                        "message": item.message,
                        "external_ref": item.external_ref,
                    }
                    for item in runtime_errors[:5]
                ],
                "checkpoint_conflict": checkpoint_error is not None,
                "dry_run": task.dry_run,
            }

            if manual_risk is not None:
                risk_error = self._risk_error(manual_risk)
                async with self.session_factory() as session:
                    await self.risk_guard.handle_platform_risk(
                        session=session,
                        run_id=run.id,
                        connector_instance_id=context.instance.id,
                        platform_account_id=task.platform_account_id,
                        platform=context.definition.platform,
                        error=risk_error,
                        actor=task.triggered_by,
                        metadata=metadata,
                        raw_error_code=manual_risk.source_error_code,
                        standard_error_code=manual_risk.standard_error_code,
                        risk_level=manual_risk.severity,
                        retryable=False,
                        response_context=manual_risk.metadata,
                        collected_count=collected_count,
                        inserted_count=inserted_count,
                        duplicate_count=duplicate_count,
                        failed_count=1 + int(checkpoint_error is not None),
                        checkpoint_after=(
                            collection.checkpoint
                            if checkpoint_committed
                            else None
                        ),
                    )
                await self.settle(
                    reservations,
                    actual_items=collected_count,
                    actual_comments=actual_comments,
                    completed=True,
                )
                async with self.session_factory() as session:
                    await SourceService(session).mark_error(
                        context.source.id,
                        manual_risk.standard_error_code,
                    )
                    risk_run = await ConnectorRunService(session).get(run.id)
                self.log_result(
                    context=context,
                    run=risk_run,
                    failed_count=risk_run.failed_count,
                    latency=monotonic() - started,
                    risk_action=risk_error.event.action.value,
                )
                return RuntimeResult(
                    run_id=risk_run.id,
                    status=risk_run.status,
                    signal_ids=tuple(signal_ids),
                    collected_count=risk_run.collected_count,
                    inserted_count=risk_run.inserted_count,
                    duplicate_count=risk_run.duplicate_count,
                    failed_count=risk_run.failed_count,
                    fetch_status=collection.metadata.get("fetch_status"),
                )

            failed_count = len(runtime_errors) + int(
                checkpoint_error is not None
            )
            if failed_count and normalized:
                target_status = ConnectorRunStatus.PARTIAL
            elif failed_count:
                target_status = ConnectorRunStatus.FAILED
            else:
                target_status = ConnectorRunStatus.SUCCEEDED

            error_code = (
                "checkpoint_conflict"
                if checkpoint_error is not None
                else ("partial_parse_failure" if runtime_errors else None)
            )
            error_message = (
                "Checkpoint 版本冲突，已提交信号将在重试时按幂等规则去重"
                if checkpoint_error is not None
                else ("部分条目或评论处理失败" if runtime_errors else None)
            )
            async with self.session_factory() as session:
                finalized = await ConnectorRunService(session).finalize(
                    run_id=run.id,
                    target_status=target_status,
                    collected_count=collected_count,
                    inserted_count=inserted_count,
                    duplicate_count=duplicate_count,
                    failed_count=failed_count,
                    retry_count=task.retry_count,
                    error_code=error_code,
                    error_message=error_message,
                    checkpoint_after=(
                        collection.checkpoint
                        if checkpoint_committed
                        else None
                    ),
                    metadata=metadata,
                )
            async with self.session_factory() as session:
                source_service = SourceService(session)
                if target_status in {
                    ConnectorRunStatus.SUCCEEDED,
                    ConnectorRunStatus.PARTIAL,
                }:
                    await source_service.mark_success(context.source.id)
                else:
                    await source_service.mark_error(
                        context.source.id,
                        error_code or "collection_failed",
                    )
            await self.settle(
                reservations,
                actual_items=collected_count,
                actual_comments=actual_comments,
                completed=True,
            )
            self.log_result(
                context=context,
                run=finalized,
                failed_count=failed_count,
                latency=monotonic() - started,
                risk_action=None,
            )
            return RuntimeResult(
                run_id=finalized.id,
                status=finalized.status,
                signal_ids=tuple(signal_ids),
                collected_count=finalized.collected_count,
                inserted_count=finalized.inserted_count,
                duplicate_count=finalized.duplicate_count,
                failed_count=finalized.failed_count,
                fetch_status=collection.metadata.get("fetch_status"),
            )
        except PlatformRiskError as exc:
            if not claimed:
                raise
            async with self.session_factory() as session:
                await self.risk_guard.handle_platform_risk(
                    session=session,
                    run_id=run.id,
                    connector_instance_id=context.instance.id,
                    platform_account_id=task.platform_account_id,
                    platform=context.definition.platform,
                    error=exc,
                    actor=task.triggered_by,
                    metadata={
                        "task": task.to_dict(),
                        "budget": {
                            "reservations": self.budget_metadata(reservations),
                            "actual_items": 0,
                            "actual_comments": 0,
                            "completed": True,
                        },
                    },
                )
            await self.settle(
                reservations,
                actual_items=0,
                actual_comments=0,
                completed=True,
            )
            async with self.session_factory() as session:
                await SourceService(session).mark_error(
                    context.source.id,
                    exc.event.code,
                )
                risk_run = await ConnectorRunService(session).get(run.id)
            self.log_result(
                context=context,
                run=risk_run,
                failed_count=1,
                latency=monotonic() - started,
                risk_action=exc.event.action.value,
            )
            return RuntimeResult(
                run_id=risk_run.id,
                status=risk_run.status,
                signal_ids=(),
                collected_count=0,
                inserted_count=0,
                duplicate_count=0,
                failed_count=1,
            )
        except BudgetExceededError:
            async with self.session_factory() as session:
                await ConnectorRunService(session).finalize(
                    run_id=run.id,
                    target_status=ConnectorRunStatus.CANCELLED,
                    failed_count=0,
                    retry_count=task.retry_count,
                    error_code="budget_rejected",
                    error_message="采集预算不足，未启动网络请求",
                    metadata={
                        "task": task.to_dict(),
                        "budget": {"rejected": True},
                    },
                )
            raise
        except Exception as exc:
            if claimed:
                code = (
                    exc.code
                    if isinstance(exc, ConnectorFetchError)
                    else "collector_execution_failed"
                )
                async with self.session_factory() as session:
                    failed = await ConnectorRunService(session).finalize(
                        run_id=run.id,
                        target_status=ConnectorRunStatus.FAILED,
                        collected_count=collected_count,
                        inserted_count=inserted_count,
                        duplicate_count=duplicate_count,
                        failed_count=1,
                        retry_count=task.retry_count,
                        error_code=code,
                        error_message=self.safe_error_message(exc),
                        metadata={
                            "task": task.to_dict(),
                            "budget": {
                                "reservations": self.budget_metadata(
                                    reservations
                                ),
                                "actual_items": collected_count,
                                "actual_comments": actual_comments,
                                "completed": True,
                            },
                        },
                    )
                await self.settle(
                    reservations,
                    actual_items=collected_count,
                    actual_comments=actual_comments,
                    completed=True,
                )
                async with self.session_factory() as session:
                    await SourceService(session).mark_error(
                        context.source.id,
                        code,
                    )
                self.log_result(
                    context=context,
                    run=failed,
                    failed_count=1,
                    latency=monotonic() - started,
                    risk_action=None,
                )
                return RuntimeResult(
                    run_id=failed.id,
                    status=failed.status,
                    signal_ids=tuple(signal_ids),
                    collected_count=collected_count,
                    inserted_count=inserted_count,
                    duplicate_count=duplicate_count,
                    failed_count=1,
                )
            if reservations:
                await self.settle(
                    reservations,
                    actual_items=0,
                    actual_comments=0,
                    completed=False,
                )
            raise

    @staticmethod
    def _manual_risk(
        signals: tuple[CollectionRiskSignal, ...],
    ) -> CollectionRiskSignal | None:
        return next(
            (item for item in signals if item.requires_manual_review),
            None,
        )

    @staticmethod
    def _risk_error(signal: CollectionRiskSignal) -> PlatformRiskError:
        decision = classify_platform_error(
            code=signal.standard_error_code,
            message=signal.message,
        )
        return PlatformRiskError(
            RiskEvent.now(
                platform=signal.platform,
                account_id=None,
                code=signal.standard_error_code,
                message=signal.message,
                disposition=decision.disposition,
                action=decision.action,
            )
        )

    @staticmethod
    def requested_comment_budget(
        config: dict[str, object],
        mode: str,
        requested_items: int,
    ) -> int:
        if mode != "comments" and config.get("include_comments") is not True:
            return 0
        value = config.get("comment_limit", 20)
        if isinstance(value, bool) or not isinstance(value, int):
            per_item_limit = 20
        else:
            per_item_limit = max(0, min(50, value))
        return per_item_limit * max(0, requested_items)

    @staticmethod
    def reported_comment_count(metadata: dict[str, object]) -> int:
        value = metadata.get("failed_comment_map_count", 0)
        if isinstance(value, bool) or not isinstance(value, int):
            return 0
        return max(0, value)

    @staticmethod
    def budget_metadata(
        reservations: tuple[BudgetReservation, ...],
    ) -> list[dict[str, object]]:
        return [
            {
                "budget_id": str(item.budget_id),
                "usage_date": item.usage_date,
                "reserved_items": item.reserved_items,
                "reserved_comments": item.reserved_comments,
            }
            for item in reservations
        ]
