"""Регрессия публичного трекинга: изоляция, повторы и локальная квитанция."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.api.public import _claim_hits
from app.config import get_settings
from app.main import create_app
from tests.integration.test_public_claim import _captcha, _dsn, _landing_acceptance

pytestmark = pytest.mark.integration


def test_tracking_privacy_and_scenario4(seeded: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", seeded)
    monkeypatch.setenv("APP_ENV", "test")
    get_settings.cache_clear()
    _claim_hits.clear()
    with psycopg.connect(_dsn(seeded)) as conn:
        city_id, region = conn.execute("select id,region_code from cities order by id limit 1").fetchone()
    try:
        with TestClient(create_app()) as client:
            agent = SimpleNamespace(enabled=True, submit=Mock(), submit_client_reply=Mock(), stop=AsyncMock())
            client.app.state.agent = agent
            challenge, answer = _captcha(client)
            response = client.post(
                "/api/public/claim",
                json={
                    "contact": {"email": "guest@example.com", "region_code": region, "city_id": city_id},
                    "text": "Отказали в кредитной карте без объяснений. Почему?",
                    "consent": True,
                    "captcha": {"id": challenge, "answer": answer},
                },
            )
            assert response.status_code == 201, response.text
            created = response.json()
            token = created["tracking_token"]
            path = f"/api/public/track/{token}"
            assert response.headers["cache-control"] == "no-store"
            with psycopg.connect(_dsn(seeded)) as conn:
                parent, run_id = conn.execute(
                    "select id,run_id from signals where tracking_token=%s", (token,)
                ).fetchone()
            assert agent.submit.call_args.args[0] == parent
            _landing_acceptance(seeded, parent)
            viewed = client.get(path)
            assert viewed.status_code == 200
            view = viewed.json()
            assert any(note["template_code"] == "ack_received" for note in view["notifications"])
            assert any(item["step"] == "team_working" and item["done"] for item in view["timeline"])
            assert viewed.headers["referrer-policy"] == "no-referrer"
            assert "noindex" in viewed.headers["x-robots-tag"]
            assert "Request received" in client.get(path, headers={"Accept-Language": "en-US"}).text
            with psycopg.connect(_dsn(seeded)) as conn:
                incident = conn.execute(
                    "select incident_id from incident_signals where signal_id=%s", (parent,)
                ).fetchone()[0]
                # Уведомление другого клиента того же инцидента не должно быть доступно.
                conn.execute(
                    "insert into notifications(run_id,recipient_type,incident_id,channel_code,template_code,body,status) values (%s,'client',%s,'landing','ack_received','Чужое личное сообщение','sent')",
                    (run_id, incident),
                )
                conn.execute(
                    "insert into notifications(run_id,recipient_type,signal_id,channel_code,template_code,body,status) values (%s,'client',%s,'landing','ack_received','Ещё не отправлено','queued')",
                    (run_id, parent),
                )
            view = client.get(path).json()
            assert "Чужое личное сообщение" not in json.dumps(view, ensure_ascii=False)
            assert "Ещё не отправлено" not in json.dumps(view, ensure_ascii=False)
            assert all("client_id" not in note and "incident_id" not in note for note in view["notifications"])
            missing = client.get("/api/public/track/" + "z" * 32)
            assert missing.status_code == 404
            assert "z" * 32 not in missing.text
            assert missing.json()["instance"] == "/api/public/track/{token}"
    finally:
        get_settings.cache_clear()
        _claim_hits.clear()
