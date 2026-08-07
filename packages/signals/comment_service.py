from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from packages.connectors.base import CollectedComment
from packages.signals.comment_repository import CommentIngestionResult, RawSignalCommentRepository


class RawSignalCommentService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = RawSignalCommentRepository(session)

    async def ingest(
        self,
        *,
        raw_signal_id: UUID,
        comment: CollectedComment,
    ) -> CommentIngestionResult:
        async with self.session.begin():
            return await self.repository.insert(raw_signal_id=raw_signal_id, comment=comment)
