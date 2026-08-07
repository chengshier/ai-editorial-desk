from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from packages.connectors.mediacrawler_adapter.errors import (
    MediaCrawlerAdapterError,
    MediaCrawlerErrorCode,
)
from packages.connectors.mediacrawler_adapter.incremental import (
    IncrementalOrdering,
    filter_tieba_new_items,
    get_incremental_spec,
    supported_incremental_specs,
    tieba_watermark_reached,
)
from packages.connectors.mediacrawler_adapter.protocol import (
    MediaCrawlerCheckpoint,
    MediaCrawlerCounters,
    MediaCrawlerInvocation,
    MediaCrawlerMode,
    MediaCrawlerPlatform,
    MediaCrawlerResultEnvelope,
    MediaCrawlerResultStatus,
)
from packages.connectors.mediacrawler_adapter.resilience import (
    MediaCrawlerResilienceRunner,
    ResumePageRunner,
)


def _invocation(
    platform: MediaCrawlerPlatform = MediaCrawlerPlatform.WEIBO,
    *,
    limit: int = 20,
    checkpoint: MediaCrawlerCheckpoint | None = None,
) -> MediaCrawlerInvocation:
    return MediaCrawlerInvocation(
        run_id=uuid4(),
        platform=platform,
        mode=MediaCrawlerMode.SEARCH,
        source_id=uuid4(),
        keyword="AI",
        requested_limit=limit,
        checkpoint=checkpoint,
        timeout_seconds=30,
    )


def _weibo_item(index: int, *, created: int = 1786086000) -> dict[str, object]:
    return {
        "note_id": f"post-{index}",
        "content": f"fixture-{index}",
        "create_time": created + index,
        "note_url": f"https://m.weibo.cn/detail/post-{index}",
        "liked_count": index,
        "comments_count": index,
        "shared_count": index,
    }


def _envelope(
    invocation: MediaCrawlerInvocation,
    items: list[dict[str, object]],
) -> MediaCrawlerResultEnvelope:
    now = datetime.now(UTC)
    return MediaCrawlerResultEnvelope(
        protocol_version="1.1",
        run_id=invocation.run_id,
        platform=invocation.platform,
        status=MediaCrawlerResultStatus.SUCCESS,
        items=items,
        counters=MediaCrawlerCounters(items=len(items)),
        started_at=now,
        finished_at=now,
    )


class SequenceRunner:
    def __init__(self, values: list[MediaCrawlerResultEnvelope | Exception]) -> None:
        self.values = list(values)
        self.calls: list[MediaCrawlerInvocation] = []

    async def run(self, invocation: MediaCrawlerInvocation) -> MediaCrawlerResultEnvelope:
        self.calls.append(invocation)
        if not self.values:
            raise AssertionError("unexpected runner call")
        value = self.values.pop(0)
        if isinstance(value, Exception):
            raise value
        return value.model_copy(
            update={
                "run_id": invocation.run_id,
                "platform": invocation.platform,
            }
        )


def test_seven_platform_incremental_matrix_is_explicit() -> None:
    specs = {item.platform: item for item in supported_incremental_specs()}
    assert set(specs) == set(MediaCrawlerPlatform)
    assert all(item.search_incremental for item in specs.values())
    assert all(not item.detail_incremental for item in specs.values())
    assert all(not item.creator_incremental for item in specs.values())
    assert specs[MediaCrawlerPlatform.BAIDU_TIEBA].ordering is IncrementalOrdering.TIME_DESC
    assert all(
        item.ordering is IncrementalOrdering.UNKNOWN
        for platform, item in specs.items()
        if platform is not MediaCrawlerPlatform.BAIDU_TIEBA
    )
    assert specs[MediaCrawlerPlatform.KUAISHOU].replays_prefix_pages is True


def test_resume_page_runner_uses_pinned_cli_start_hook() -> None:
    invocation = _invocation(
        checkpoint=MediaCrawlerCheckpoint(
            platform=MediaCrawlerPlatform.WEIBO,
            mode=MediaCrawlerMode.SEARCH,
            page=4,
        )
    )
    runner = ResumePageRunner(home=Path("."), python_executable="python")
    command = runner._build_command(Path("main.py"), Path("data"), invocation)
    assert command[command.index("--start") + 1] == "4"


async def test_partial_run_returns_safe_resume_checkpoint_and_second_run_resumes() -> None:
    first_invocation = _invocation(limit=20)
    first_page = _envelope(first_invocation, [_weibo_item(index) for index in range(10)])
    first_runner = SequenceRunner(
        [
            first_page,
            MediaCrawlerAdapterError(
                MediaCrawlerErrorCode.RATE_LIMITED,
                "MediaCrawler platform rate limit detected",
            ),
        ]
    )
    partial = await MediaCrawlerResilienceRunner(
        first_runner,
        sleep=_no_sleep,
        jitter=lambda: 0.0,
    ).run(first_invocation)

    assert partial.status is MediaCrawlerResultStatus.PARTIAL
    assert len(partial.items) == 10
    assert partial.checkpoint is not None
    assert partial.checkpoint.page == 2
    assert partial.risk_events[0].standard_error_code == "RATE_LIMITED"
    assert partial.risk_events[0].checkpoint_safe_to_commit is True
    assert partial.risk_events[0].retryable is False

    second_invocation = _invocation(limit=10, checkpoint=partial.checkpoint)
    second_page = _envelope(second_invocation, [_weibo_item(100), _weibo_item(101)])
    second_runner = SequenceRunner([second_page])
    resumed = await MediaCrawlerResilienceRunner(
        second_runner,
        sleep=_no_sleep,
        jitter=lambda: 0.0,
    ).run(second_invocation)

    assert second_runner.calls[0].checkpoint is not None
    assert second_runner.calls[0].checkpoint.page == 2
    assert [item["note_id"] for item in resumed.items] == ["post-100", "post-101"]
    assert resumed.checkpoint is not None
    assert resumed.checkpoint.page == 1
    assert resumed.checkpoint.metadata["cycle_complete"] is True


async def test_unknown_ordering_never_uses_time_watermark_for_early_stop() -> None:
    future = datetime.now(UTC) + timedelta(days=30)
    invocation = _invocation(
        limit=2,
        checkpoint=MediaCrawlerCheckpoint(
            platform=MediaCrawlerPlatform.WEIBO,
            mode=MediaCrawlerMode.SEARCH,
            page=1,
            latest_published_at=future,
        ),
    )
    runner = SequenceRunner([_envelope(invocation, [_weibo_item(1), _weibo_item(2)])])
    result = await MediaCrawlerResilienceRunner(
        runner,
        sleep=_no_sleep,
        jitter=lambda: 0.0,
    ).run(invocation)
    assert len(result.items) == 2


def test_tieba_time_desc_watermark_stops_only_at_safe_suffix() -> None:
    watermark = datetime(2026, 8, 7, 10, tzinfo=UTC)
    checkpoint = MediaCrawlerCheckpoint(
        platform=MediaCrawlerPlatform.BAIDU_TIEBA,
        mode=MediaCrawlerMode.SEARCH,
        page=1,
        last_external_id="known",
        latest_published_at=watermark,
    )
    items = [
        {"note_id": "new", "publish_time": (watermark + timedelta(hours=1)).timestamp()},
        {"note_id": "known", "publish_time": watermark.timestamp()},
        {"note_id": "old", "publish_time": (watermark - timedelta(hours=1)).timestamp()},
    ]
    assert tieba_watermark_reached(items=items, checkpoint=checkpoint) is True
    assert filter_tieba_new_items(items=items, checkpoint=checkpoint) == [items[0]]
    assert get_incremental_spec("baidu_tieba").ordering is IncrementalOrdering.TIME_DESC


async def test_technical_failure_has_bounded_retry_but_platform_risk_does_not() -> None:
    invocation = _invocation(limit=1)
    success = _envelope(invocation, [_weibo_item(1)])
    technical_runner = SequenceRunner(
        [
            MediaCrawlerAdapterError(
                MediaCrawlerErrorCode.BROWSER_DISCONNECTED,
                "MediaCrawler browser process disconnected",
            ),
            success,
        ]
    )
    technical = await MediaCrawlerResilienceRunner(
        technical_runner,
        sleep=_no_sleep,
        jitter=lambda: 0.0,
    ).run(invocation)
    assert technical.status is MediaCrawlerResultStatus.SUCCESS
    assert len(technical_runner.calls) == 2

    risk_runner = SequenceRunner(
        [
            MediaCrawlerAdapterError(
                MediaCrawlerErrorCode.RATE_LIMITED,
                "MediaCrawler platform rate limit detected",
            )
        ]
    )
    with pytest.raises(MediaCrawlerAdapterError) as risk:
        await MediaCrawlerResilienceRunner(
            risk_runner,
            sleep=_no_sleep,
            jitter=lambda: 0.0,
        ).run(invocation)
    assert risk.value.code == "RATE_LIMITED"
    assert len(risk_runner.calls) == 1


async def _no_sleep(_: float) -> None:
    return None
