"""T-108: таблица вне allow-list не читается."""

from fastapi.testclient import TestClient

from app.main import create_app


def test_db_rows_forbidden_outside_allow_list() -> None:
    with TestClient(create_app()) as client:
        res = client.get("/api/engine/db/tables/users/rows")
    assert res.status_code == 403
