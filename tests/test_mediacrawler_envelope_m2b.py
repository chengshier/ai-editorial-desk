from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from packages.connectors.mediacrawler_adapter.connector import MediaCrawlerConnector
from packages.connectors.mediacrawler_adapter.errors import (
    MediaCrawlerAdapterError,
    MediaCrawlerErrorCode,
)
from packages.connectors.mediacrawler_adapter.protocol import (
    MEDIACRAWLER_PROTOCOL_VERSION,
    MediaCrawlerCheckpoint,
    MediaCrawlerCounters,
    MediaCrawlerMode,
    MediaCrawlerPlatform,
    MediaCrawlerResultEnvelope,
    MediaCrawlerResultStatus,
)


def _envelope(items, comments):  # type: ignore[no-untyped-def]
    now = datetime.now(UTC)
    return MediaCrawlerResultEnvelope(
        protocol_version=MEDIACRAWLER_PROTOCOL_VERSION,
        run_id=uuid4(),
        platform=MediaCrawlerPlatform.WEIBO,
        status=MediaCrawlerResultStatus.PARTIAL,
        items=items,
        comments=comments,
        checkpoint=MediaCrawlerCheckpoint(
            platform=MediaCrawlerPlatform.WEIBO,
            mode=MediaCrawlerMode.SEARCH,
            page=2,
            cursor={"fixture": "next"},
        ),
        counters=MediaCrawlerCounters(items=len(items), comments=len(comments)),
        warnings=[],
        risk_events=[],
        errors=[],
        started_at=now,
        finished_at=now,
    )


def _connector() -> MediaCrawlerConnector:
    return MediaCrawlerConnector(
        adapter=SimpleNamespace(
            settings=SimpleNamespace(mediacrawler_timeout_seconds=30)
        )  # type: ignore[arg-type]
    )


def test_result_envelope_allows_bounded_item_and_comment_partial_mapping() -> None:
    result = _connector()._to_collection_result(  # noqa: SLF001
        _envelope(
            [
                {
                    "note_id": "post-good",
                    "content": "good",
                    "create_time": 1786086000,
                    "note_url": "https://m.weibo.cn/detail/post-good",
                },
                {"content": "missing identity"},
            ],
            [
                {
                    "comment_id": "comment-good",
                    "note_id": "post-good",
                    "content": "good comment",
                    "create_time": 1786086010,
                },
                {"comment_id": "comment-bad", "content": "missing note id"},
            ],
        ),
        allow_comments=True,
    )
    assert len(result.signals) == 1
    assert len(result.comments) == 1
    assert result.metadata["mapped_count"] == 1
    assert result.metadata["failed_map_count"] == 1
    assert result.metadata["mapped_comment_count"] == 1
    assert result.metadata["failed_comment_map_count"] == 1
    assert [item.code for item in result.errors] == [
        "mediacrawler_item_unmapped",
        "mediacrawler_comment_unmapped",
    ]


def test_result_envelope_fails_when_platform_format_is_completely_unrecognized() -> None:
    with pytest.raises(MediaCrawlerAdapterError) as error:
        _connector()._to_collection_result(  # noqa: SLF001
            _envelope([{"unexpected": "shape"}], []),
            allow_comments=False,
        )
    assert error.value.code == MediaCrawlerErrorCode.PARSE_ERROR.value


def test_unexpected_comments_are_not_mapped_when_collection_was_disabled() -> None:
    result = _connector()._to_collection_result(  # noqa: SLF001
        _envelope(
            [
                {
                    "note_id": "post-good",
                    "content": "good",
                    "note_url": "https://m.weibo.cn/detail/post-good",
                }
            ],
            [
                {
                    "comment_id": "comment-unexpected",
                    "note_id": "post-good",
                    "content": "must not persist",
                }
            ],
        ),
        allow_comments=False,
    )
    assert result.comments == ()
    assert result.metadata["failed_comment_map_count"] == 1
    assert result.errors[0].code == "mediacrawler_unexpected_comments"
