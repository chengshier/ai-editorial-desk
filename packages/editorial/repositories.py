from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.models import (
    EditorialScoreOverrideRecord,
    EditorialScoreRecord,
    EditorialScoreSourceType,
    EditorialScoringRunRecord,
    EventTrendSnapshotRecord,
)


class TrendSnapshotRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, snapshot_id: UUID) -> EventTrendSnapshotRecord | None:
        return await self.session.get(EventTrendSnapshotRecord, snapshot_id)

    async def latest_for_event(self, event_id: UUID) -> EventTrendSnapshotRecord | None:
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
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def list_for_event(self, event_id: UUID) -> Sequence[EventTrendSnapshotRecord]:
        statement = (
            select(EventTrendSnapshotRecord)
            .where(EventTrendSnapshotRecord.event_id == event_id)
            .order_by(
                EventTrendSnapshotRecord.window_end_at.desc(),
                EventTrendSnapshotRecord.created_at.desc(),
                EventTrendSnapshotRecord.id.desc(),
            )
        )
        return list((await self.session.scalars(statement)).all())

    async def insert_if_absent(
        self,
        snapshot: EventTrendSnapshotRecord,
    ) -> tuple[EventTrendSnapshotRecord, bool]:
        values = {
            "event_id": snapshot.event_id,
            "calculation_version": snapshot.calculation_version,
            "window_start_at": snapshot.window_start_at,
            "window_end_at": snapshot.window_end_at,
            "signal_count": snapshot.signal_count,
            "new_signal_count": snapshot.new_signal_count,
            "source_count": snapshot.source_count,
            "platform_count": snapshot.platform_count,
            "signal_velocity": snapshot.signal_velocity,
            "interaction_velocity": snapshot.interaction_velocity,
            "cross_source": snapshot.cross_source,
            "cross_platform": snapshot.cross_platform,
            "semantic_novelty": snapshot.semantic_novelty,
            "cn_gap": snapshot.cn_gap,
            "update_value": snapshot.update_value,
            "feature_availability": snapshot.feature_availability,
            "component_metrics": snapshot.component_metrics,
            "input_hash": snapshot.input_hash,
        }
        statement = (
            insert(EventTrendSnapshotRecord)
            .values(**values)
            .on_conflict_do_nothing(
                index_elements=[
                    EventTrendSnapshotRecord.event_id,
                    EventTrendSnapshotRecord.calculation_version,
                    EventTrendSnapshotRecord.window_start_at,
                    EventTrendSnapshotRecord.window_end_at,
                    EventTrendSnapshotRecord.input_hash,
                ]
            )
            .returning(EventTrendSnapshotRecord.id)
        )
        created_id = (await self.session.execute(statement)).scalar_one_or_none()
        if created_id is not None:
            created = await self.session.get(EventTrendSnapshotRecord, created_id)
            if created is None:
                raise RuntimeError("Trend Snapshot 写入成功后未找到记录")
            return created, True
        existing_statement = select(EventTrendSnapshotRecord).where(
            EventTrendSnapshotRecord.event_id == snapshot.event_id,
            EventTrendSnapshotRecord.calculation_version == snapshot.calculation_version,
            EventTrendSnapshotRecord.window_start_at == snapshot.window_start_at,
            EventTrendSnapshotRecord.window_end_at == snapshot.window_end_at,
            EventTrendSnapshotRecord.input_hash == snapshot.input_hash,
        )
        existing = (await self.session.execute(existing_statement)).scalar_one_or_none()
        if existing is None:
            raise RuntimeError("Trend Snapshot 幂等冲突后未找到既有记录")
        return existing, False


class EditorialScoringRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(self, run: EditorialScoringRunRecord) -> None:
        self.session.add(run)

    async def get_for_update(self, run_id: UUID) -> EditorialScoringRunRecord | None:
        statement = (
            select(EditorialScoringRunRecord)
            .where(EditorialScoringRunRecord.id == run_id)
            .with_for_update()
        )
        return (await self.session.execute(statement)).scalar_one_or_none()


class EditorialScoreRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, score_id: UUID) -> EditorialScoreRecord | None:
        return await self.session.get(EditorialScoreRecord, score_id)

    async def list_for_event(self, event_id: UUID) -> Sequence[EditorialScoreRecord]:
        statement = (
            select(EditorialScoreRecord)
            .where(EditorialScoreRecord.event_id == event_id)
            .order_by(EditorialScoreRecord.created_at.desc(), EditorialScoreRecord.id.desc())
        )
        return list((await self.session.scalars(statement)).all())

    async def latest_human_for_event(self, event_id: UUID) -> EditorialScoreRecord | None:
        statement = (
            select(EditorialScoreRecord)
            .where(
                EditorialScoreRecord.event_id == event_id,
                EditorialScoreRecord.source_type == EditorialScoreSourceType.HUMAN,
            )
            .order_by(EditorialScoreRecord.created_at.desc(), EditorialScoreRecord.id.desc())
            .limit(1)
        )
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def latest_ai_for_event(self, event_id: UUID) -> EditorialScoreRecord | None:
        statement = (
            select(EditorialScoreRecord)
            .where(
                EditorialScoreRecord.event_id == event_id,
                EditorialScoreRecord.source_type == EditorialScoreSourceType.AI,
            )
            .order_by(EditorialScoreRecord.created_at.desc(), EditorialScoreRecord.id.desc())
            .limit(1)
        )
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def get_ai_by_input(
        self,
        *,
        event_id: UUID,
        score_template: str,
        score_template_version: str,
        scoring_version: str,
        input_hash: str,
    ) -> EditorialScoreRecord | None:
        statement = select(EditorialScoreRecord).where(
            EditorialScoreRecord.event_id == event_id,
            EditorialScoreRecord.source_type == EditorialScoreSourceType.AI,
            EditorialScoreRecord.score_template == score_template,
            EditorialScoreRecord.score_template_version == score_template_version,
            EditorialScoreRecord.scoring_version == scoring_version,
            EditorialScoreRecord.input_hash == input_hash,
        )
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def insert_ai_if_absent(
        self,
        *,
        values: dict[str, object],
    ) -> tuple[EditorialScoreRecord, bool]:
        statement = (
            insert(EditorialScoreRecord)
            .values(**values)
            .on_conflict_do_nothing(
                index_elements=[
                    EditorialScoreRecord.event_id,
                    EditorialScoreRecord.score_template,
                    EditorialScoreRecord.score_template_version,
                    EditorialScoreRecord.scoring_version,
                    EditorialScoreRecord.input_hash,
                ],
                index_where=text("source_type = 'ai'"),
            )
            .returning(EditorialScoreRecord.id)
        )
        created_id = (await self.session.execute(statement)).scalar_one_or_none()
        if created_id is not None:
            created = await self.session.get(EditorialScoreRecord, created_id)
            if created is None:
                raise RuntimeError("Editorial Score 写入成功后未找到记录")
            return created, True
        existing = await self.get_ai_by_input(
            event_id=values["event_id"],  # type: ignore[arg-type]
            score_template=str(values["score_template"]),
            score_template_version=str(values["score_template_version"]),
            scoring_version=str(values["scoring_version"]),
            input_hash=str(values["input_hash"]),
        )
        if existing is None:
            raise RuntimeError("Editorial Score 幂等冲突后未找到既有记录")
        return existing, False

    def add_human(self, score: EditorialScoreRecord) -> None:
        self.session.add(score)


class EditorialOverrideRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(self, override: EditorialScoreOverrideRecord) -> None:
        self.session.add(override)

    async def list_for_event(self, event_id: UUID) -> Sequence[EditorialScoreOverrideRecord]:
        statement = (
            select(EditorialScoreOverrideRecord)
            .join(
                EditorialScoreRecord,
                EditorialScoreRecord.id == EditorialScoreOverrideRecord.editorial_score_id,
            )
            .where(EditorialScoreRecord.event_id == event_id)
            .order_by(
                EditorialScoreOverrideRecord.created_at.asc(),
                EditorialScoreOverrideRecord.id.asc(),
            )
        )
        return list((await self.session.scalars(statement)).all())
