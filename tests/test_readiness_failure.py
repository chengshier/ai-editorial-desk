from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from apps.api import main
from packages.database.exceptions import DatabaseUnavailableError


async def unavailable_database() -> None:
    raise DatabaseUnavailableError("postgresql+asyncpg://user:secret@localhost/database")


def test_readiness_failure_does_not_leak_credentials(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(main, "check_database_ready", unavailable_database)

    response = TestClient(main.app).get("/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready", "database": "unavailable"}
    assert "secret" not in response.text
    assert "postgresql" not in response.text
