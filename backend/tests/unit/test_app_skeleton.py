"""Каркас: health отвечает даже без БД, 501-заглушки — problem+json с карточкой, WS принимает подписку."""

from __future__ import annotations

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
    with TestClient(create_app()) as c:
        r = c.delete("/api/sim/runs/1")  # заглушка T-031 (archive/delete); baseline реализован в T-040
    assert r.status_code == 501
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["card"].startswith("T-")


def test_search_stub_501() -> None:
    with TestClient(create_app()) as c:
        r = c.get("/api/search", params={"q": "SIG-000001"})
    assert r.status_code == 501
    assert r.json()["card"] == "T-230"


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
