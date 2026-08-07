from datetime import UTC, datetime

from packages.connectors.base import CollectedComment
from packages.signals.idempotency import build_comment_idempotency_key


def test_comment_idempotency_prefers_platform_content_and_comment_id() -> None:
    base = CollectedComment(
        platform="weibo",
        content_external_id="post-1",
        external_comment_id="comment-1",
        author_id="author-1",
        author_name="author",
        text="same text",
        published_at=datetime(2026, 8, 7, tzinfo=UTC),
        like_count=1,
        parent_comment_id=None,
    )
    changed_text = CollectedComment(
        platform=base.platform,
        content_external_id=base.content_external_id,
        external_comment_id=base.external_comment_id,
        author_id=base.author_id,
        author_name=base.author_name,
        text="changed text",
        published_at=base.published_at,
        like_count=2,
        parent_comment_id=None,
    )
    assert build_comment_idempotency_key(base) == build_comment_idempotency_key(changed_text)


def test_comment_idempotency_fallback_is_deterministic_without_comment_id() -> None:
    first = CollectedComment(
        platform="baidu_tieba",
        content_external_id="post-1",
        external_comment_id=None,
        author_id="author-1",
        author_name="author",
        text="fallback text",
        published_at=datetime(2026, 8, 7, 8, 30, tzinfo=UTC),
        like_count=None,
        parent_comment_id=None,
    )
    same = CollectedComment(
        platform=first.platform,
        content_external_id=first.content_external_id,
        external_comment_id=None,
        author_id=first.author_id,
        author_name="renamed author",
        text="fallback   text",
        published_at=first.published_at,
        like_count=None,
        parent_comment_id=None,
    )
    different = CollectedComment(
        platform=first.platform,
        content_external_id=first.content_external_id,
        external_comment_id=None,
        author_id=first.author_id,
        author_name=first.author_name,
        text="different text",
        published_at=first.published_at,
        like_count=None,
        parent_comment_id=None,
    )
    assert build_comment_idempotency_key(first) == build_comment_idempotency_key(same)
    assert build_comment_idempotency_key(first) != build_comment_idempotency_key(different)
