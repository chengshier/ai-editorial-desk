import pytest
from pydantic import ValidationError

from packages.common.config import Settings

VALID_URL = "postgresql+asyncpg://user:password@127.0.0.1:55432/database"
VALID_SECRET = "a-valid-development-secret-that-is-long-enough"


def test_settings_accept_async_postgresql_url() -> None:
    settings = Settings(
        _env_file=None,
        database_url=VALID_URL,
        app_secret_key=VALID_SECRET,
    )

    assert settings.database_url_value == VALID_URL
    assert "password" not in repr(settings.database_url)


def test_settings_reject_non_asyncpg_database_url() -> None:
    with pytest.raises(ValidationError, match="postgresql\\+asyncpg"):
        Settings(
            _env_file=None,
            database_url="postgresql://user:password@127.0.0.1/database",
            app_secret_key=VALID_SECRET,
        )
