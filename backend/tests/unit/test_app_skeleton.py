"""Каркас: health отвечает даже без БД, 501-заглушки — problem+json с карточкой, WS принимает подписку."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


def test_health_degraded_without_db(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://cx:cx@127.0.0.1:1/none")
    from app.config import get_settings
    from app.db import session as sess

    get_settings.cache_clear()
    sess.get_engine.cache_clear()
    sess.get_sessionmaker.cache_clear()
    with TestClient(create_app()) as c:
        r = c.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "degraded" and body["db"] is False and "version" in body


def test_stub_is_problem_json_501() -> None:
    from app.errors import NotImplementedYet

    app = create_app()

    @app.delete("/api/test-stub")
    async def stub() -> None:
        raise NotImplementedYet("T-040")

    with TestClient(app) as c:
        r = c.delete("/api/test-stub")
    assert r.status_code == 501
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["card"].startswith("T-")


def test_search_requires_query() -> None:
    with TestClient(create_app()) as c:
        r = c.get("/api/search")
    assert r.status_code == 422
    assert r.headers["content-type"].startswith("application/problem+json")


def test_validation_error_is_problem_json() -> None:
    with TestClient(create_app()) as c:
        r = c.get("/api/engine/db/tables/signals/rows?limit=abc")
    assert r.status_code in (422, 501)
    assert r.headers["content-type"].startswith("application/problem+json")


def test_ws_subscribe_and_ping() -> None:
    with TestClient(create_app()) as c, c.websocket_connect("/ws/stream") as ws:
        hello = ws.receive_json()
        assert hello["topic"] == "system" and hello["type"] == "hello"
        ws.send_json({"type": "subscribe", "topics": ["signals", "bogus"], "filters": {"run_id": 1}})
        sub = ws.receive_json()
        assert sub["data"]["topics"] == ["signals"]
        ws.send_json({"type": "ping"})
        assert ws.receive_json()["type"] == "pong"


@pytest.mark.parametrize(
    ("path", "card"),
    [("/api/test-v15-stub/cabinet", "T-241"), ("/api/test-v15-stub/csi", "T-247")],
)
@pytest.mark.parametrize("with_spa", [False, True])
def test_v15_stubs_are_problem_json(path: str, card: str, with_spa: bool, tmp_path: Path, monkeypatch) -> None:
    from app.config import get_settings
    from app.errors import NotImplementedYet

    dist = tmp_path / "frontend"
    if with_spa:
        (dist / "assets").mkdir(parents=True)
        (dist / "index.html").write_text("<!doctype html><title>test SPA</title>")
    monkeypatch.setenv("FRONTEND_DIST", str(dist))
    get_settings.cache_clear()
    app = create_app()

    @app.get(path)
    async def stub() -> None:
        raise NotImplementedYet(card)

    # Test-only API объявляется перед catchall, как настоящие routers в create_app.
    app.router.routes.insert(0, app.router.routes.pop())
    assert any(getattr(route, "name", None) == "spa" for route in app.router.routes) == with_spa
    with TestClient(app) as client:
        response = client.get(path)
    assert response.status_code == 501
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["status"] == 501
    assert response.json()["card"] == card
    assert response.json()["instance"] == path
