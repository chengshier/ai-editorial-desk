from __future__ import annotations

import ast
import asyncio
import copy
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, List, Tuple

import pytest

CORE_PATH = (
    Path(__file__).parents[1]
    / "third_party"
    / "MediaCrawler"
    / "media_platform"
    / "bilibili"
    / "core.py"
)


class _Logger:
    def info(self, _: str) -> None:
        return None

    def warning(self, _: str) -> None:
        return None


class _KeywordVar:
    def set(self, _: str) -> None:
        return None


class _Store:
    async def update_bilibili_video(self, _: object) -> None:
        return None

    async def update_up_info(self, _: object) -> None:
        return None


class _SearchClient:
    def __init__(self) -> None:
        self.calls: list[tuple[int, int]] = []

    async def search_video_by_keyword(self, **kwargs):  # type: ignore[no-untyped-def]
        page = int(kwargs["page"])
        page_size = int(kwargs["page_size"])
        self.calls.append((page, page_size))
        first = (page - 1) * page_size + 1
        return {
            "result": [
                {"aid": aid}
                for aid in range(first, first + page_size)
            ]
        }


def _load_harness_class():  # type: ignore[no-untyped-def]
    tree = ast.parse(CORE_PATH.read_text(encoding="utf-8"))
    selected: list[ast.stmt] = []
    search_method: ast.AsyncFunctionDef | None = None

    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = {
                target.id
                for target in node.targets
                if isinstance(target, ast.Name)
            }
            if "BILI_SEARCH_MAX_PAGE_SIZE" in names:
                selected.append(copy.deepcopy(node))
        elif isinstance(node, ast.FunctionDef) and node.name in {
            "_build_bili_search_pagination",
            "_bili_search_page_item_limit",
        }:
            selected.append(copy.deepcopy(node))
        elif isinstance(node, ast.ClassDef) and node.name == "BilibiliCrawler":
            for child in node.body:
                if (
                    isinstance(child, ast.AsyncFunctionDef)
                    and child.name == "search_by_keywords"
                ):
                    search_method = copy.deepcopy(child)
                    break

    assert search_method is not None
    harness_class = ast.ClassDef(
        name="BilibiliSearchHarness",
        bases=[],
        keywords=[],
        body=[search_method],
        decorator_list=[],
    )
    module = ast.fix_missing_locations(
        ast.Module(body=[*selected, harness_class], type_ignores=[])
    )
    namespace = {
        "Dict": Dict,
        "List": List,
        "Tuple": Tuple,
        "asyncio": asyncio,
        "utils": SimpleNamespace(logger=_Logger()),
        "source_keyword_var": _KeywordVar(),
        "SearchOrderType": SimpleNamespace(DEFAULT="default"),
        "bilibili_store": _Store(),
    }
    exec(compile(module, str(CORE_PATH), "exec"), namespace)
    return namespace["BilibiliSearchHarness"]


async def _run_search(limit: int, *, start_page: int = 1):
    harness_class = _load_harness_class()
    crawler = harness_class()
    client = _SearchClient()
    processed: list[int] = []

    crawler.bili_client = client

    async def get_video_info_task(
        aid: int,
        bvid: str,
        semaphore: asyncio.Semaphore,
    ) -> dict[str, dict[str, int]]:
        del bvid, semaphore
        return {"View": {"aid": aid}}

    async def get_bilibili_video(
        video_item: dict[str, dict[str, int]],
        semaphore: asyncio.Semaphore,
    ) -> None:
        del semaphore
        processed.append(video_item["View"]["aid"])

    async def batch_get_video_comments(_: list[int]) -> None:
        return None

    crawler.get_video_info_task = get_video_info_task
    crawler.get_bilibili_video = get_bilibili_video
    crawler.batch_get_video_comments = batch_get_video_comments

    globals_dict = crawler.search_by_keywords.__func__.__globals__
    globals_dict["config"] = SimpleNamespace(
        CRAWLER_MAX_NOTES_COUNT=limit,
        START_PAGE=start_page,
        KEYWORDS="fixture",
        MAX_CONCURRENCY_NUM=1,
        CRAWLER_MAX_SLEEP_SEC=0,
    )

    await asyncio.wait_for(crawler.search_by_keywords(), timeout=1)
    return client.calls, processed


@pytest.mark.parametrize("limit", [1, 3, 5, 20])
async def test_low_volume_search_uses_requested_limit_as_real_page_size(limit: int) -> None:
    calls, processed = await _run_search(limit)

    assert calls == [(1, limit)]
    assert processed == list(range(1, limit + 1))
    assert calls[0][1] <= limit


async def test_requested_limit_five_never_requests_twenty_then_truncates() -> None:
    calls, processed = await _run_search(5)

    assert calls == [(1, 5)]
    assert processed == [1, 2, 3, 4, 5]
    assert all(page_size == 5 for _, page_size in calls)


@pytest.mark.parametrize(
    ("limit", "expected_calls"),
    [
        (21, [(1, 20), (2, 20)]),
        (45, [(1, 20), (2, 20), (3, 20)]),
    ],
)
async def test_over_single_page_limit_keeps_stable_page_size_and_finite_pagination(
    limit: int,
    expected_calls: list[tuple[int, int]],
) -> None:
    calls, processed = await _run_search(limit)

    assert calls == expected_calls
    assert len(calls) == len(set(page for page, _ in calls))
    assert all(page_size == 20 for _, page_size in calls)
    assert processed == list(range(1, limit + 1))


async def test_start_page_and_page_size_define_non_overlapping_window() -> None:
    calls, processed = await _run_search(5, start_page=3)

    assert calls == [(3, 5)]
    assert processed == [11, 12, 13, 14, 15]


def test_upstream_force_to_twenty_assignment_is_removed() -> None:
    source = CORE_PATH.read_text(encoding="utf-8")

    assert "config.CRAWLER_MAX_NOTES_COUNT = bili_limit_count" not in source
    assert "page_size=bili_page_size" in source
    assert "for page_offset in range(page_count)" in source
