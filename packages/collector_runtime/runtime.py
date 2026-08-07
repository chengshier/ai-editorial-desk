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
from packages.connectors.http import ConnectorFetchError
from packages.database.models import ConnectorRunStatus
from packages.risk_guard.models import PlatformRiskError
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

        try:
            async with self.session_factory() as session:
                reservations = await CollectionBudgetService(session).reserve(
                    platform=context.definition.platform,
                    connector_instance_id=context.instance.id,
                    connector_type=context.definition.connector_type,
                    platform_account_id=task.platform_account_id,
                    source_id=context.source.id,
                    requested_items=task.requested_limit,
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
                )
            )

            normalized = [
                NormalizedSignal.from_connector_signal(
                    source_id=context.source.id,
                    connector_instance_id=context.instance.id,
                    connector_run_id=run.id,
                    connector_type=context.definition.connector_type,
                    signal=signal,
                    canonical_url=normalize_http_url(signal.canonical_url or signal.url),
                )
                for signal in collection.signals
            ]
            collected_count = len(collection.signals)
            if not task.dry_run:
                for offset in range(0, len(normalized), INGESTION_BATCH_SIZE):
                    batch = normalized[offset : offset + INGESTION_BATCH_SIZE]
                    async with self.session_factory() as session:
                        results = await RawSignalService(session).ingest_many(batch)
                    signal_ids.extend(item.signal_id for item in results)
                    inserted_count += sum(1 for item in results if item.created)
                    duplicate_count += sum(1 for item in results if item.duplicate)

            checkpoint_error: VersionConflictError | None = None
            if (
                not task.dry_run
                and checkpoint is not None
                and collection.checkpoint is not None
                and collection.signals
            ):
                try:
                    await self.advance_checkpoint(
                        checkpoint_id=checkpoint.id,
                        expected_version=checkpoint.version,
                        checkpoint_data=collection.checkpoint,
                        signals=collection.signals,
                    )
                except VersionConflictError as exc:
                    checkpoint_error = exc

            failed_count = len(collection.errors) + int(checkpoint_error is not None)
            if failed_count and normalized:
                target_status = ConnectorRunStatus.PARTIAL
            elif failed_count:
                target_status = ConnectorRunStatus.FAILED
            else:
                target_status = ConnectorRunStatus.SUCCEEDED
            error_code = (
                "checkpoint_conflict"
                if checkpoint_error is not None
                else ("partial_parse_failure" if collection.errors else None)
            )
            error_message = (
                "Checkpoint 版本冲突，已提交信号将在重试时按幂等规则去重"
                if checkpoint_error is not None
                else ("部分条目解析失败" if collection.errors else None)
            )
            metadata = {
                **collection.metadata,
                "task": task.to_dict(),
                "budget": {
                    "reservations": budget_metadata,
                    "actual_items": collected_count,
                    "completed": True,
                },
                "error_samples": [
                    {
                        "code": item.code,
                        "message": item.message,
                        "external_ref": item.external_ref,
                    }
                    for item in collection.errors[:5]
                ],
                "dry_run": task.dry_run,
            }
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
                        if not task.dry_run and checkpoint_error is None
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
                            "completed": True,
                        },
                    },
                )
            await self.settle(reservations, actual_items=0, completed=True)
            async with self.session_factory() as session:
                await SourceService(session).mark_error(context.source.id, exc.event.code)
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
                    metadata={"task": task.to_dict(), "budget": {"rejected": True}},
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
                                "reservations": self.budget_metadata(reservations),
                                "actual_items": collected_count,
                                "completed": True,
                            },
                        },
                    )
                await self.settle(
                    reservations,
                    actual_items=collected_count,
                    completed=True,
                )
                async with self.session_factory() as session:
                    await SourceService(session).mark_error(context.source.id, code)
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
                await self.settle(reservations, actual_items=0, completed=False)
            raise

    @staticmethod
    def budget_metadata(reservations: tuple[BudgetReservation, ...]) -> list[dict[str, object]]:
        return [
            {
                "budget_id": str(item.budget_id),
                "usage_date": item.usage_date,
                "reserved_items": item.reserved_items,
            }
            for item in reservations
        ]
