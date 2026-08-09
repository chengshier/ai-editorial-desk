from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.models import (
    DraftClaimReferenceRecord,
    DraftGenerationMode,
    DraftGenerationRunRecord,
    DraftSourceType,
    EditorialDraftRecord,
    EditorialPackRecord,
    EventCardRecord,
)


class EventCardRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, card_id: UUID) -> EventCardRecord | None:
        return await self.session.get(EventCardRecord, card_id)

    async def list_for_event(self, event_id: UUID) -> Sequence[EventCardRecord]:
        statement = (
            select(EventCardRecord)
            .where(EventCardRecord.event_id == event_id)
            .order_by(EventCardRecord.created_at.desc(), EventCardRecord.id.desc())
        )
        return list((await self.session.scalars(statement)).all())

    async def insert_if_absent(
        self, values: dict[str, object]
    ) -> tuple[EventCardRecord, bool]:
        statement = (
            insert(EventCardRecord)
            .values(**values)
            .on_conflict_do_nothing(
                index_elements=[
                    EventCardRecord.event_id,
                    EventCardRecord.card_version,
                    EventCardRecord.input_hash,
                ]
            )
            .returning(EventCardRecord.id)
        )
        created_id = (await self.session.execute(statement)).scalar_one_or_none()
        if created_id is not None:
            item = await self.session.get(EventCardRecord, created_id)
            if item is None:
                raise RuntimeError("Event Card 写入后未找到记录")
            return item, True
        existing = (
            await self.session.execute(
                select(EventCardRecord).where(
                    EventCardRecord.event_id == values["event_id"],
                    EventCardRecord.card_version == values["card_version"],
                    EventCardRecord.input_hash == values["input_hash"],
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            raise RuntimeError("Event Card 幂等冲突后未找到记录")
        return existing, False


class EditorialPackRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, pack_id: UUID) -> EditorialPackRecord | None:
        return await self.session.get(EditorialPackRecord, pack_id)

    async def list_for_event(self, event_id: UUID) -> Sequence[EditorialPackRecord]:
        statement = (
            select(EditorialPackRecord)
            .where(EditorialPackRecord.event_id == event_id)
            .order_by(EditorialPackRecord.created_at.desc(), EditorialPackRecord.id.desc())
        )
        return list((await self.session.scalars(statement)).all())

    async def insert_if_absent(
        self, values: dict[str, object]
    ) -> tuple[EditorialPackRecord, bool]:
        statement = (
            insert(EditorialPackRecord)
            .values(**values)
            .on_conflict_do_nothing(
                index_elements=[
                    EditorialPackRecord.event_id,
                    EditorialPackRecord.event_card_id,
                    EditorialPackRecord.pack_version,
                    EditorialPackRecord.input_hash,
                ]
            )
            .returning(EditorialPackRecord.id)
        )
        created_id = (await self.session.execute(statement)).scalar_one_or_none()
        if created_id is not None:
            item = await self.session.get(EditorialPackRecord, created_id)
            if item is None:
                raise RuntimeError("Editorial Pack 写入后未找到记录")
            return item, True
        existing = (
            await self.session.execute(
                select(EditorialPackRecord).where(
                    EditorialPackRecord.event_id == values["event_id"],
                    EditorialPackRecord.event_card_id == values["event_card_id"],
                    EditorialPackRecord.pack_version == values["pack_version"],
                    EditorialPackRecord.input_hash == values["input_hash"],
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            raise RuntimeError("Editorial Pack 幂等冲突后未找到记录")
        return existing, False


class DraftGenerationRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(self, run: DraftGenerationRunRecord) -> None:
        self.session.add(run)

    async def claim_apply(
        self, values: dict[str, object]
    ) -> tuple[DraftGenerationRunRecord, bool]:
        statement = (
            insert(DraftGenerationRunRecord)
            .values(**values)
            .on_conflict_do_nothing(
                index_elements=[
                    DraftGenerationRunRecord.event_id,
                    DraftGenerationRunRecord.event_card_id,
                    DraftGenerationRunRecord.editorial_pack_id,
                    DraftGenerationRunRecord.draft_type,
                    DraftGenerationRunRecord.prompt_version,
                    DraftGenerationRunRecord.schema_version,
                    DraftGenerationRunRecord.input_hash,
                ],
                index_where=text("mode = 'apply'"),
            )
            .returning(DraftGenerationRunRecord.id)
        )
        created_id = (await self.session.execute(statement)).scalar_one_or_none()
        if created_id is not None:
            run = await self.session.get(DraftGenerationRunRecord, created_id)
            if run is None:
                raise RuntimeError("Draft Generation Run 写入后未找到")
            return run, True
        existing = (
            await self.session.execute(
                select(DraftGenerationRunRecord).where(
                    DraftGenerationRunRecord.event_id == values["event_id"],
                    DraftGenerationRunRecord.event_card_id == values["event_card_id"],
                    DraftGenerationRunRecord.editorial_pack_id == values["editorial_pack_id"],
                    DraftGenerationRunRecord.draft_type == values["draft_type"],
                    DraftGenerationRunRecord.prompt_version == values["prompt_version"],
                    DraftGenerationRunRecord.schema_version == values["schema_version"],
                    DraftGenerationRunRecord.input_hash == values["input_hash"],
                    DraftGenerationRunRecord.mode == DraftGenerationMode.APPLY,
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            raise RuntimeError("Draft Generation Run 幂等冲突后未找到")
        return existing, False

    async def get(self, run_id: UUID) -> DraftGenerationRunRecord | None:
        return await self.session.get(DraftGenerationRunRecord, run_id)

    async def get_for_update(self, run_id: UUID) -> DraftGenerationRunRecord | None:
        statement = (
            select(DraftGenerationRunRecord)
            .where(DraftGenerationRunRecord.id == run_id)
            .with_for_update()
        )
        return (await self.session.execute(statement)).scalar_one_or_none()


class EditorialDraftRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, draft_id: UUID) -> EditorialDraftRecord | None:
        return await self.session.get(EditorialDraftRecord, draft_id)

    async def get_for_update(self, draft_id: UUID) -> EditorialDraftRecord | None:
        statement = (
            select(EditorialDraftRecord)
            .where(EditorialDraftRecord.id == draft_id)
            .with_for_update()
        )
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def list_for_event(self, event_id: UUID) -> Sequence[EditorialDraftRecord]:
        statement = (
            select(EditorialDraftRecord)
            .where(EditorialDraftRecord.event_id == event_id)
            .order_by(EditorialDraftRecord.created_at.desc(), EditorialDraftRecord.id.desc())
        )
        return list((await self.session.scalars(statement)).all())

    async def list_chain(self, chain_id: UUID) -> Sequence[EditorialDraftRecord]:
        statement = (
            select(EditorialDraftRecord)
            .where(EditorialDraftRecord.draft_chain_id == chain_id)
            .order_by(EditorialDraftRecord.draft_version.asc())
        )
        return list((await self.session.scalars(statement)).all())

    async def max_chain_version(self, chain_id: UUID) -> int:
        statement = select(func.max(EditorialDraftRecord.draft_version)).where(
            EditorialDraftRecord.draft_chain_id == chain_id
        )
        value = (await self.session.execute(statement)).scalar_one()
        return int(value or 0)

    async def get_ai_by_input(
        self,
        *,
        event_card_id: UUID,
        editorial_pack_id: UUID,
        draft_type: object,
        prompt_version: str,
        schema_version: str,
        input_hash: str,
    ) -> EditorialDraftRecord | None:
        statement = select(EditorialDraftRecord).where(
            EditorialDraftRecord.event_card_id == event_card_id,
            EditorialDraftRecord.editorial_pack_id == editorial_pack_id,
            EditorialDraftRecord.draft_type == draft_type,
            EditorialDraftRecord.prompt_version == prompt_version,
            EditorialDraftRecord.schema_version == schema_version,
            EditorialDraftRecord.input_hash == input_hash,
            EditorialDraftRecord.source_type == DraftSourceType.AI,
        )
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def insert_ai_if_absent(
        self, values: dict[str, object]
    ) -> tuple[EditorialDraftRecord, bool]:
        statement = (
            insert(EditorialDraftRecord)
            .values(**values)
            .on_conflict_do_nothing(
                index_elements=[
                    EditorialDraftRecord.event_card_id,
                    EditorialDraftRecord.editorial_pack_id,
                    EditorialDraftRecord.draft_type,
                    EditorialDraftRecord.prompt_version,
                    EditorialDraftRecord.schema_version,
                    EditorialDraftRecord.input_hash,
                ],
                index_where=text("source_type = 'ai'"),
            )
            .returning(EditorialDraftRecord.id)
        )
        created_id = (await self.session.execute(statement)).scalar_one_or_none()
        if created_id is not None:
            item = await self.session.get(EditorialDraftRecord, created_id)
            if item is None:
                raise RuntimeError("AI Draft 写入后未找到")
            return item, True
        existing = await self.get_ai_by_input(
            event_card_id=values["event_card_id"],  # type: ignore[arg-type]
            editorial_pack_id=values["editorial_pack_id"],  # type: ignore[arg-type]
            draft_type=values["draft_type"],
            prompt_version=str(values["prompt_version"]),
            schema_version=str(values["schema_version"]),
            input_hash=str(values["input_hash"]),
        )
        if existing is None:
            raise RuntimeError("AI Draft 幂等冲突后未找到")
        return existing, False

    def add_human(self, draft: EditorialDraftRecord) -> None:
        self.session.add(draft)


class DraftClaimReferenceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(self, reference: DraftClaimReferenceRecord) -> None:
        self.session.add(reference)

    async def list_for_draft(self, draft_id: UUID) -> Sequence[DraftClaimReferenceRecord]:
        statement = (
            select(DraftClaimReferenceRecord)
            .where(DraftClaimReferenceRecord.draft_id == draft_id)
            .order_by(
                DraftClaimReferenceRecord.section_key.asc(),
                DraftClaimReferenceRecord.created_at.asc(),
                DraftClaimReferenceRecord.id.asc(),
            )
        )
        return list((await self.session.scalars(statement)).all())
