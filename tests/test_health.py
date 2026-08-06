from fastapi.testclient import TestClient

from apps.api import main


async def ready_database() -> None:
    return None


def test_health_check() -> None:
    response = TestClient(main.app).get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_readiness_checks_database(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(main, "check_database_ready", ready_database)

    response = TestClient(main.app).get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "database": "available"}
