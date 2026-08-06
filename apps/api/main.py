from datetime import UTC, datetime

from fastapi import FastAPI

from packages.common.config import get_settings

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    debug=settings.app_debug,
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


@app.get("/ready", tags=["system"])
async def readiness_check() -> dict[str, str]:
    """Initial readiness endpoint; database checks are added in M1."""

    return {"status": "ready"}
