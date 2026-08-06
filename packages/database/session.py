import asyncio
from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from packages.common.config import get_settings
from packages.database.exceptions import DatabaseOperationError, DatabaseUnavailableError


@lru_cache(maxsize=1)
def get_async_engine() -> AsyncEngine:
    """Build the process-wide async engine from deployment settings."""

    settings = get_settings()
    return create_async_engine(
        settings.database_url_value,
        echo=settings.database_echo,
        pool_pre_ping=True,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_timeout=settings.database_pool_timeout_seconds,
    )


@lru_cache(maxsize=1)
def get_async_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Return the process-wide session factory."""

    return async_sessionmaker(
        bind=get_async_engine(),
        class_=AsyncSession,
        autoflush=False,
        expire_on_commit=False,
    )


async def get_database_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency that owns one SQLAlchemy session lifecycle."""

    session_factory = get_async_sessionmaker()
    async with session_factory() as session:
        try:
            yield session
        except SQLAlchemyError as exc:
            await session.rollback()
            raise DatabaseOperationError("database operation failed") from exc


async def check_database_ready(*, timeout_seconds: float | None = None) -> None:
    """Execute a bounded dependency check without exposing connection details."""

    settings = get_settings()
    timeout = timeout_seconds or settings.database_ready_timeout_seconds
    try:
        async with asyncio.timeout(timeout):
            async with get_async_engine().connect() as connection:
                await connection.execute(text("SELECT 1"))
    except (TimeoutError, SQLAlchemyError, OSError) as exc:
        raise DatabaseUnavailableError("database is unavailable") from exc


async def dispose_database() -> None:
    """Dispose pooled connections and clear factories for tests or shutdown."""

    if get_async_engine.cache_info().currsize:
        await get_async_engine().dispose()
    get_async_sessionmaker.cache_clear()
    get_async_engine.cache_clear()
