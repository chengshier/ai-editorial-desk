from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from packages.common.config import get_settings
from packages.database.exceptions import DatabaseUnavailableError
from packages.database.session import check_database_ready, dispose_database

settings = get_settings()


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    del application
    yield
    await dispose_database()


app = FastAPI(
    title=settings.app_name,
    version="0.2.0",
    debug=settings.app_debug,
    lifespan=lifespan,
)


@app.get("/health", tags=["system"])
async def health_check() -> dict[str, str]:
    """Return a dependency-free liveness response."""

    return {
        "status": "ok",
        "service": settings.app_name,
        "environment": settings.app_env,
        "timestamp": datetime.now(UTC).isoformat(),
    }


@app.get("/ready", tags=["system"], response_model=None)
async def readiness_check() -> dict[str, str] | JSONResponse:
    """Report readiness only when PostgreSQL answers within the configured timeout."""

    try:
        await check_database_ready()
    except DatabaseUnavailableError:
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "database": "unavailable"},
        )
    return {"status": "ready", "database": "available"}
