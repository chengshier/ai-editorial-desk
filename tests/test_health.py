from fastapi.testclient import TestClient

from apps.api import main


async def ready_database() -> None:
    return None


def test_health_check() -> None:
    response = TestClient(main.app).get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_local_vite_origin_is_allowed_by_cors() -> None:
    response = TestClient(main.app).options(
        "/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_readiness_checks_database(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(main, "check_database_ready", ready_database)

    response = TestClient(main.app).get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "database": "available"}
