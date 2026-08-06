from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    database_url: str = (
        "postgresql+asyncpg://ai_editorial:change-me@127.0.0.1:55432/ai_editorial"
    )
    app_secret_key: str = Field(default="development-only-change-me", min_length=16)

    mediacrawler_home: str = "third_party/MediaCrawler"
    mediacrawler_python: str = "python"
    mediacrawler_timeout_seconds: int = Field(default=900, ge=30, le=7200)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
