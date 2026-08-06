from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    """Deployment-level settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "AI Editorial Desk"
    app_env: str = "development"
    app_debug: bool = True
    app_host: str = "127.0.0.1"
    app_port: int = 8000

    database_url: SecretStr
    app_secret_key: SecretStr = Field(min_length=32)
    app_admin_token: SecretStr = Field(min_length=24)
    database_echo: bool = False
    database_pool_size: int = Field(default=5, ge=1, le=50)
    database_max_overflow: int = Field(default=10, ge=0, le=100)
    database_pool_timeout_seconds: float = Field(default=10.0, gt=0, le=120)
    database_ready_timeout_seconds: float = Field(default=2.0, gt=0, le=30)

    mediacrawler_home: str = "third_party/MediaCrawler"
    mediacrawler_python: str = "python"
    mediacrawler_timeout_seconds: int = Field(default=900, ge=30, le=7200)

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: SecretStr) -> SecretStr:
        url = make_url(value.get_secret_value())
        if url.drivername != "postgresql+asyncpg":
            raise ValueError("DATABASE_URL must use the postgresql+asyncpg driver")
        if not url.database:
            raise ValueError("DATABASE_URL must include a database name")
        return value

    @property
    def database_url_value(self) -> str:
        """Return the URL for trusted infrastructure code without logging it."""

        return self.database_url.get_secret_value()

    @property
    def admin_token_value(self) -> str:
        """Return the internal admin token only for constant-time verification."""

        return self.app_admin_token.get_secret_value()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
