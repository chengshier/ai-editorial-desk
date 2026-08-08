from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from packages.database.models import ConnectorValidationStatus
from scripts import check_m2_smoke_environment as preflight


def _budget(**overrides):  # type: ignore[no-untyped-def]
    values = {
        "enabled": True,
        "max_runs_per_day": 3,
        "max_items_per_run": 5,
        "max_items_per_day": 15,
        "max_comments_per_run": 5,
        "max_comments_per_day": 15,
        "max_concurrency": 1,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_safe_budget_shape_accepts_only_m2d_caps() -> None:
    assert preflight._safe_budget_shape(_budget()) is True
    assert preflight._safe_budget_shape(_budget(max_runs_per_day=4)) is False
    assert preflight._safe_budget_shape(_budget(max_items_per_run=6)) is False
    assert preflight._safe_budget_shape(_budget(max_comments_per_run=6)) is False
    assert preflight._safe_budget_shape(_budget(max_concurrency=2)) is False


def test_budget_request_check_is_read_only_shape_evaluation() -> None:
    budget = _budget(max_items_per_run=5, max_comments_per_run=5)

    assert preflight._budget_allows_request(
        budget,
        requested_limit=5,
        comment_limit=5,
    ) is True
    assert preflight._budget_allows_request(
        budget,
        requested_limit=6,
        comment_limit=0,
    ) is False


def test_validation_status_expires_old_implementation() -> None:
    current = "mediacrawler-m2c-v1"
    assert (
        preflight._latest_validation_status(None, implementation_version=current)
        is ConnectorValidationStatus.NOT_TESTED
    )
    old_record = SimpleNamespace(
        implementation_version="old-version",
        status=ConnectorValidationStatus.PASSED,
    )
    assert (
        preflight._latest_validation_status(old_record, implementation_version=current)
        is ConnectorValidationStatus.EXPIRED
    )


def test_result_only_exposes_ready_blocked_and_safe_reasons() -> None:
    payload = preflight._result(
        [
            preflight._ready("database", "reachable"),
            preflight._blocked("cdp", "localhost port is not listening"),
        ]
    )

    assert payload["status"] == "BLOCKED"
    assert payload["real_network_started"] is False
    assert payload["checks"] == [
        {"name": "database", "status": "READY", "reason": "reachable"},
        {
            "name": "cdp",
            "status": "BLOCKED",
            "reason": "localhost port is not listening",
        },
    ]


def test_preflight_source_has_no_platform_network_or_runtime_execution() -> None:
    source = Path(preflight.__file__).read_text(encoding="utf-8")
    forbidden = (
        "CollectorRuntime",
        "build_smoke_registry",
        "playwright",
        "httpx",
        "bilibili.com",
        "zhihu.com",
        "weibo.cn",
        "context.cookies",
        "credential_ref).",
    )

    for marker in forbidden:
        assert marker not in source
    assert "socket.create_connection" in source
    assert '"127.0.0.1"' in source
    assert "EXPECTED_CDP_PORT = 9222" in source


def test_preflight_never_returns_reference_or_path_values() -> None:
    source = Path(preflight.__file__).read_text(encoding="utf-8")

    assert '"browser_profile_ref"' not in source
    assert '"credential_ref"' not in source
    assert '"profile_path"' not in source
    assert '"database_url"' not in source
