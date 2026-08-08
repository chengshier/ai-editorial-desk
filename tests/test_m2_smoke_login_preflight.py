from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from scripts import check_m2_smoke_login as login_preflight


def test_login_preflight_requires_explicit_confirmation(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setattr(
        login_preflight,
        "get_settings",
        lambda: SimpleNamespace(app_env="development"),
    )

    assert (
        login_preflight._human_gate("operator", "wrong")
        == "login-only preflight requires --confirm M2D_LOGIN_PREFLIGHT"
    )
    assert login_preflight._human_gate("automation", "M2D_LOGIN_PREFLIGHT") is not None


def test_login_preflight_subprocess_environment_excludes_application_secrets(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("DATABASE_URL", "secret-database-url")
    monkeypatch.setenv("APP_ADMIN_TOKEN", "secret-admin-token")
    monkeypatch.setenv("PATH", "safe-path")

    environment = login_preflight._safe_subprocess_environment()

    assert environment["PATH"] == "safe-path"
    assert "DATABASE_URL" not in environment
    assert "APP_ADMIN_TOKEN" not in environment


def test_login_helper_only_reads_local_existing_cdp_cookie_names() -> None:
    helper = (
        Path(login_preflight.__file__).parents[1]
        / "packages"
        / "connectors"
        / "mediacrawler_adapter"
        / "login_preflight_entry"
        / "main.py"
    ).read_text(encoding="utf-8")

    assert "connect_over_cdp" in helper
    assert "127.0.0.1" in helper
    assert ".cookies([args.origin])" in helper
    assert 'cookie.get("name"' in helper
    assert "httpx" not in helper
    assert "requests" not in helper
    for forbidden in (
        ".goto(",
        ".request(",
        ".post(",
        "new_page(",
        "add_cookies(",
        "CollectorRuntime",
        "search_by_keywords",
        "get_specified",
        "batch_get",
    ):
        assert forbidden not in helper


def test_login_preflight_never_prints_reference_or_cookie_values() -> None:
    source = Path(login_preflight.__file__).read_text(encoding="utf-8")
    helper = (
        Path(login_preflight.__file__).parents[1]
        / "packages"
        / "connectors"
        / "mediacrawler_adapter"
        / "login_preflight_entry"
        / "main.py"
    ).read_text(encoding="utf-8")

    assert "credential_ref" not in source
    assert "browser_profile_ref" not in source
    assert 'cookie.get("value"' not in helper
    assert '"cookies"' not in helper
    assert "real_network_started" in source
