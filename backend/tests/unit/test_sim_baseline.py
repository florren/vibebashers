"""T-040: снимок baseline честно недоступен, пока нет pg_dump."""

from fastapi.testclient import TestClient

from app.main import create_app


def test_baseline_status_is_unavailable() -> None:
    with TestClient(create_app()) as client:
        res = client.get("/api/sim/baseline")
    assert res.status_code == 200
    assert res.json()["available"] is False


def test_baseline_restore_conflicts_without_snapshot() -> None:
    with TestClient(create_app()) as client:
        res = client.post("/api/sim/baseline/restore")
    assert res.status_code == 409
