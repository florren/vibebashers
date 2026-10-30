"""T-269: изоляция публичного origin, пассивная защита и штатная анонимная обработка."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.agent.graph import process_signal
from app.config import get_settings
from app.main import create_app
from app.public_chat import create_public_app
from tests.helpers import MOCK_PROFILE, dsn, mock_chain
from tests.integration.test_hitl_continuity import patch_db

pytestmark = pytest.mark.integration


def test_public_chat_isolation_ingest_and_answers(seeded: str, conn: Any, monkeypatch: Any) -> None:
    monkeypatch.setenv("DATABASE_URL", seeded)
    get_settings.cache_clear()
    try:
        client = TestClient(create_public_app())
        for path in [
            "/api/settings",
            "/api/signals",
            "/api/hitl/queue",
            "/docs",
            "/openapi.json",
            "/finance",
            "/api/public/feed",
        ]:
            assert client.get(path).status_code == 404, path
        boot = client.get("/api/personal/session")
        assert boot.status_code == 200, boot.text
        assert "HttpOnly" in boot.headers["set-cookie"] and "SameSite=strict" in boot.headers["set-cookie"]
        assert "frame-ancestors" in boot.headers["content-security-policy"]
        data = boot.json()
        assert data["products"] and data["regions"] and data["cities"]
        payload = {
            "text": "Отказали в кредитной карте. Объясните условия, я ещё не клиент.",
            "request_id": str(uuid.uuid4()),
            "form_token": data["form_token"],
            "product_code": "credit_card",
            "display_name": "Любитель походов",
        }
        for name in ("a" * 121, "Плохое\nимя", "Имя\x00"):
            assert client.post("/api/personal/messages", json={**payload, "display_name": name}).status_code == 422
        assert client.post("/api/personal/messages", json=payload).status_code == 429
        assert client.post("/api/personal/messages", json=payload).headers["retry-after"]
        assert (
            client.post(
                "/api/personal/messages", json=payload, headers={"Origin": "https://attacker.example"}
            ).status_code
            == 403
        )
        assert (
            client.post("/api/personal/messages", json={**payload, "website": "https://bot.example"}).status_code == 403
        )
        assert client.post("/api/personal/messages", json={**payload, "client_id": 50}).status_code == 422
        conn.execute("update personal_chat_sessions set created_at=now()-interval '3 seconds'")
        response = client.post("/api/personal/messages", json=payload)
        assert response.status_code == 202, response.text
        assert client.post("/api/personal/messages", json=payload).json() == response.json()
        assert client.post("/api/personal/messages", json={**payload, "text": "Другой текст"}).status_code == 409
        assert client.post("/api/personal/messages", json={**payload, "display_name": "Другое имя"}).status_code == 409
        row = conn.execute(
            "select id,client_id,origin,meta,channel_subtype from signals where public_id=%s",
            (response.json()["public_id"],),
        ).fetchone()
        assert (
            row
            and row[1] is None
            and row[2] == "landing"
            and row[3]["tags"] == ["ui_pers_demo"]
            and row[3]["visitor_name"] == payload["display_name"]
            and row[4] == "ui_pers_demo"
        )
        assert conn.execute("select count(*) from personal_chat_messages").fetchone()[0] == 1

        async def run() -> None:
            async with await psycopg.AsyncConnection.connect(dsn(seeded)) as ac:
                state = await process_signal(ac, signal_id=row[0], chain=mock_chain(), profile=MOCK_PROFILE)
                assert state
                assert state.get("client") is None
                assert state["context"]["form_context"]["visitor_name"] == payload["display_name"]

        asyncio.run(run())
        history = client.get("/api/personal/messages").json()
        assert history["messages"][0]["public_id"] == response.json()["public_id"]
        assert history["messages"][0]["display_name"] == payload["display_name"]
        assert client.get("/api/personal/session").json()["display_name"] == payload["display_name"]
        assert history["answers"] and all(set(a) == {"id", "text", "at"} for a in history["answers"])
        assert client.get("/api/personal/messages").headers["referrer-policy"] == "no-referrer"
        other = TestClient(create_public_app())
        assert other.get("/api/personal/session").json()["display_name"] == ""
        assert other.get("/api/personal/messages").json() == {"messages": [], "answers": []}
        assert (
            other.post("/api/personal/messages", json={**payload, "request_id": str(uuid.uuid4())}).status_code == 403
        )
        patch_db(monkeypatch, seeded)
        feed = TestClient(create_app()).get("/api/signals", params={"run_id": "all", "tag": "ui_pers_demo"}).json()
        assert [x["id"] for x in feed["items"]] == [row[0]]
        assert feed["items"][0]["tags"] == ["ui_pers_demo"]
        conn.execute("update personal_chat_sessions set last_message_at=now()-interval '3 seconds'")
        followup = {
            **payload,
            "request_id": str(uuid.uuid4()),
            "text": "Какие есть альтернативы?",
            "display_name": None,
        }
        assert client.post("/api/personal/messages", json=followup).status_code == 202
        child = conn.execute("select signal_id from personal_chat_messages order by id desc limit 1").fetchone()[0]

        async def run_child() -> None:
            async with await psycopg.AsyncConnection.connect(dsn(seeded)) as ac:
                state = await process_signal(ac, signal_id=child, chain=mock_chain(), profile=MOCK_PROFILE)
                assert state and state["context"]["conversation"][0]["user"] == payload["text"]
                assert state["context"]["form_context"]["product_code"] == "credit_card"
                assert state["context"]["form_context"]["visitor_name"] == payload["display_name"]

        asyncio.run(run_child())
        conn.execute("update personal_chat_sessions set last_message_at=now()-interval '3 seconds'")
        assert (
            client.post(
                "/api/personal/messages", json={**followup, "request_id": str(uuid.uuid4()), "display_name": ""}
            ).status_code
            == 202
        )
        assert client.get("/api/personal/session").json()["display_name"] == ""
        assert client.get("/api/personal/messages").json()["messages"][0]["display_name"] == payload["display_name"]
        assert client.post("/api/personal/reset", json={}).status_code == 204
        assert client.get("/api/personal/messages").status_code == 401
    finally:
        get_settings.cache_clear()


def test_body_boundaries_and_voice_session(seeded: str, conn: Any, monkeypatch: Any) -> None:
    monkeypatch.setenv("DATABASE_URL", seeded)
    get_settings.cache_clear()
    try:
        client = TestClient(create_public_app())
        assert client.post("/api/stt/transcribe", content=b"1234").status_code == 401
        client.get("/api/personal/session")
        assert (
            client.post(
                "/api/personal/messages",
                content=iter([b" " * 20000, b" " * 20000]),
                headers={"content-type": "application/json"},
            ).status_code
            == 413
        )
        assert client.post("/api/stt/transcribe", content=b"\0" * 1000002).status_code == 413
        assert client.post("/api/stt/transcribe", content=b"RIFFbadfile").status_code == 422
        assert (
            client.post("/api/stt/transcribe", content=b"abc", headers={"origin": "https://evil.example"}).status_code
            == 403
        )
    finally:
        get_settings.cache_clear()
