from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from packages.connectors.base import CollectedComment
from packages.database.models.signals import RawSignalCommentRecord
from packages.database.types import sanitize_context
from packages.signals.idempotency import build_comment_idempotency_key


@dataclass(slots=True, frozen=True)
class CommentIngestionResult:
    comment_id: UUID
    created: bool
    duplicate: bool


class RawSignalCommentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def insert(
        self,
        *,
        raw_signal_id: UUID,
        comment: CollectedComment,
    ) -> CommentIngestionResult:
        idempotency_key = build_comment_idempotency_key(comment)
        statement = (
            insert(RawSignalCommentRecord)
            .values(
                raw_signal_id=raw_signal_id,
                platform=comment.platform,
                external_comment_id=comment.external_comment_id,
                author_id=comment.author_id,
                author_name=comment.author_name,
                text=comment.text,
                published_at=comment.published_at,
                like_count=comment.like_count,
                parent_comment_id=comment.parent_comment_id,
                raw_payload=sanitize_context(comment.raw_payload),
                idempotency_key=idempotency_key,
            )
            .on_conflict_do_nothing(
                index_elements=[RawSignalCommentRecord.idempotency_key]
            )
            .returning(RawSignalCommentRecord.id)
        )
        created_id = (await self.session.execute(statement)).scalar_one_or_none()
        if created_id is not None:
            return CommentIngestionResult(created_id, created=True, duplicate=False)
        existing_id = await self.session.scalar(
            select(RawSignalCommentRecord.id).where(
                RawSignalCommentRecord.idempotency_key == idempotency_key
            )
        )
        if existing_id is None:
            raise RuntimeError("评论幂等写入冲突后未找到既有记录")
        return CommentIngestionResult(existing_id, created=False, duplicate=True)
