from __future__ import annotations

import os
from pathlib import Path

import pytest

from packages.ai_gateway.credentials import EnvironmentCredentialResolver, load_provider_environment


def test_provider_credentials_load_project_dotenv_without_overriding_process_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider_key = "TEST_DYNAMIC_PROVIDER_KEY"
    process_key = "TEST_DYNAMIC_EXISTING_KEY"
    env_file = tmp_path / ".env"
    env_file.write_text(
        f"{provider_key}=from-dotenv\n{process_key}=from-dotenv\n",
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AI_EDITORIAL_ENV_FILE", raising=False)
    monkeypatch.delenv(provider_key, raising=False)
    monkeypatch.setenv(process_key, "from-process")
    load_provider_environment.cache_clear()

    try:
        resolver = EnvironmentCredentialResolver()

        assert resolver.configured(f"env://{provider_key}") is True
        assert resolver.resolve(f"env://{provider_key}").get_secret_value() == "from-dotenv"
        assert resolver.resolve(f"env://{process_key}").get_secret_value() == "from-process"
        assert os.getenv(process_key) == "from-process"
        assert load_provider_environment() == env_file
    finally:
        os.environ.pop(provider_key, None)
        load_provider_environment.cache_clear()


def test_provider_credentials_support_explicit_env_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider_key = "TEST_EXPLICIT_PROVIDER_KEY"
    env_file = tmp_path / "provider-secrets.env"
    env_file.write_text(f"{provider_key}=explicit-secret\n", encoding="utf-8")

    monkeypatch.setenv("AI_EDITORIAL_ENV_FILE", str(env_file))
    monkeypatch.delenv(provider_key, raising=False)
    load_provider_environment.cache_clear()

    try:
        resolver = EnvironmentCredentialResolver()

        assert resolver.configured(f"env://{provider_key}") is True
        assert resolver.resolve(f"env://{provider_key}").get_secret_value() == "explicit-secret"
        assert load_provider_environment() == env_file
    finally:
        os.environ.pop(provider_key, None)
        load_provider_environment.cache_clear()
