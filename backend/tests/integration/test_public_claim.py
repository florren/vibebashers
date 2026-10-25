"""T-119: публичные claim, captcha, track, QR бота и приём Telegram (seeded БД)."""

from __future__ import annotations

import json
import os
import re

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app

_CYRILLIC = re.compile(r"[А-Яа-яЁё]")


def _dsn(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def _captcha(client: TestClient) -> tuple[str, int]:
    response = client.get("/api/public/captcha")
    assert response.status_code == 200, response.text
    body = response.json()
    assert "answer" not in body
    assert isinstance(body["id"], str) and body["id"]
    left, right = (part.strip() for part in body["question"].split("=", 1)[0].split("+"))
    return str(body["id"]), int(left) + int(right)


def _claim(
    client: TestClient,
    *,
    region: str,
    city_id: int,
    product: str,
    consent: bool = True,
    answer: int | None = None,
    captcha_id: str | None = None,
    phone: str = "+7 900 000-11-22",
) -> httpx.Response:
    if captcha_id is None or answer is None:
        captcha_id, solved = _captcha(client)
        if answer is None:
            answer = solved
    return client.post(
        "/api/public/claim",
        json={
            "contact": {"name": "Гость", "phone": phone, "region_code": region, "city_id": city_id},
            "product_code": product,
            "text": "Не приходит смс-код для входа в приложение уже второй день",
            "consent": consent,
            "captcha": {"id": captcha_id, "answer": answer},
        },
    )


@pytest.mark.integration
def test_public_claim_track_bot_and_live_feed(seeded: str, monkeypatch: pytest.MonkeyPatch) -> None:
    os.environ["DATABASE_URL"] = seeded
    os.environ["APP_ENV"] = "test"
    get_settings.cache_clear()
    try:
        _checks(seeded, monkeypatch)
    finally:
        get_settings.cache_clear()


def _checks(dsn: str, monkeypatch: pytest.MonkeyPatch) -> None:
    with psycopg.connect(_dsn(dsn), autocommit=True) as conn:
        place = conn.execute(
            "select c.id, c.region_code from cities c join regions r on r.code = c.region_code order by c.id limit 1"
        ).fetchone()
        product = conn.execute("select code from products order by code limit 1").fetchone()
        assert place and product
        city_id, region = int(place[0]), str(place[1])
        product_code = str(product[0])

    with TestClient(create_app()) as client:
        captcha = client.get("/api/public/captcha")
        assert captcha.status_code == 200
        assert "answer" not in captcha.json()
        assert "=" in captcha.json()["question"]

        denied = _claim(
            client, region=region, city_id=city_id, product=product_code, consent=False, answer=0, captcha_id="missing"
        )
        assert denied.status_code == 422
        assert _CYRILLIC.search(denied.json()["detail"])

        wrong_id, _solved = _captcha(client)
        wrong = _claim(client, region=region, city_id=city_id, product=product_code, captcha_id=wrong_id, answer=100)
        assert wrong.status_code == 422
        assert _CYRILLIC.search(wrong.json()["detail"])

        created = _claim(client, region=region, city_id=city_id, product=product_code)
        assert created.status_code == 201, created.text
        payload = created.json()
        assert payload["public_id"].startswith("SIG-")
        assert len(payload["tracking_token"]) >= 24
        assert "<svg" in payload["qr_svg"]
        assert payload["track_url"].endswith("/track/" + payload["tracking_token"])
        token = payload["tracking_token"]

        with psycopg.connect(_dsn(dsn)) as conn:
            row = conn.execute(
                "select id, channel_code, origin, tracking_token, public_id, external_contact, external_post_id "
                "from signals where tracking_token = %s",
                (token,),
            ).fetchone()
            assert row
            parent_id = int(row[0])
            assert row[1] == "landing" and row[2] == "landing"
            assert isinstance(row[3], str) and len(row[3]) >= 24
            assert str(row[4]).startswith("SIG-")
            contact = row[5] if isinstance(row[5], dict) else json.loads(row[5])
            assert contact["city_id"] == city_id
            assert row[6] is None
            appended_before = conn.execute(
                "select count(*) from sim_events where event_type = 'signal.appended'"
            ).fetchone()
            assert appended_before

        missing = client.get("/api/public/track/" + "z" * 32)
        assert missing.status_code == 404
        assert _CYRILLIC.search(missing.json()["detail"])

        viewed = client.get(f"/api/public/track/{token}")
        assert viewed.status_code == 200, viewed.text
        view = viewed.json()
        assert view["public_id"].startswith("SIG-")
        assert view["can_append"] is False
        steps = {item["step"] for item in view["timeline"]}
        allowed = {
            "received",
            "agent_started",
            "classified",
            "incident_created",
            "team_working",
            "progress_update",
            "clarification_needed",
            "answered",
            "resolved",
            "closed",
        }
        assert steps <= allowed and "received" in steps
        for item in view["timeline"]:
            assert _TEAM_CODE.search(item["label_ru"]) is None
            text_ru = item.get("text_ru") or ""
            assert "team_" not in text_ru

        appended = client.post(
            f"/api/public/track/{token}", json={"text": "Дополняю обращение подробностями по смс-коду"}
        )
        assert appended.status_code == 202
        assert appended.content == b""

        with psycopg.connect(_dsn(dsn)) as conn:
            child = conn.execute(
                "select parent_signal_id, tracking_token from signals where parent_signal_id = %s",
                (parent_id,),
            ).fetchone()
            assert child and int(child[0]) == parent_id and child[1] is None
            appended_after = conn.execute(
                "select count(*) from sim_events where event_type = 'signal.appended'"
            ).fetchone()
            assert appended_after and appended_after[0] == appended_before[0]

        for _ in range(4):
            again = _claim(client, region=region, city_id=city_id, product=product_code)
            assert again.status_code == 201, again.text
        sixth = _claim(client, region=region, city_id=city_id, product=product_code)
        assert sixth.status_code == 422
        assert sixth.status_code != 429
        assert _CYRILLIC.search(sixth.json()["detail"])

        settings = get_settings()
        monkeypatch.setattr(settings, "telegram_bot_token", "")
        hidden = client.get("/api/public/bot/qr")
        assert hidden.status_code == 404
        secret = "super-secret-bot-token-do-not-leak"
        monkeypatch.setattr(settings, "telegram_bot_token", secret)
        qr = client.get("/api/public/bot/qr")
        assert qr.status_code == 200
        assert qr.headers["content-type"].startswith("image/svg+xml")
        assert "<svg" in qr.text
        assert secret not in qr.text

        chat_id = 424242
        started = client.post(
            "/api/internal/tgbot/inbound", json={"chat_id": chat_id, "kind": "start", "text": "/start"}
        )
        assert started.status_code == 200, started.text
        start_body = started.json()
        assert start_body["signal_id"] is None
        assert len(start_body["buttons"]) == 2
        assert {button["data"] for button in start_body["buttons"]} == {"is_client", "not_client"}

        short = client.post(
            "/api/internal/tgbot/inbound", json={"chat_id": chat_id, "kind": "free_text", "text": "коротко"}
        )
        assert short.status_code == 200 and short.json()["signal_id"] is None

        client.post("/api/internal/tgbot/inbound", json={"chat_id": chat_id, "kind": "is_client", "text": "is_client"})
        client.post(
            "/api/internal/tgbot/inbound",
            json={
                "chat_id": chat_id,
                "kind": "free_text",
                "text": "Не приходит смс-код для входа в приложение уже второй день",
            },
        )
        client.post(
            "/api/internal/tgbot/inbound",
            json={"chat_id": chat_id, "kind": "contact", "text": "+7 900 001-22-33"},
        )
        finished = client.post(
            "/api/internal/tgbot/inbound", json={"chat_id": chat_id, "kind": "region", "text": region}
        )
        assert finished.status_code == 200, finished.text
        bot = finished.json()
        assert bot["signal_id"]
        assert bot["tracking_token"] and len(bot["tracking_token"]) >= 24
        assert "SIG-" in bot["reply_text"] and f"/track/{bot['tracking_token']}" in bot["reply_text"]

        with psycopg.connect(_dsn(dsn)) as conn:
            bot_row = conn.execute(
                "select channel_code, origin, external_contact, client_id from signals where id = %s",
                (bot["signal_id"],),
            ).fetchone()
            assert bot_row
            assert bot_row[0] == "telegram_bot" and bot_row[1] == "telegram_bot"
            bot_contact = bot_row[2] if isinstance(bot_row[2], dict) else json.loads(bot_row[2])
            assert bot_contact["telegram_chat_id"] == chat_id
            assert bot_row[3] is None

        review = client.post(
            "/api/public/reviews",
            json={
                "platform": "review_portal",
                "author_nick": "demo_user",
                "text": "Комиссия за перевод списалась дважды, прошу проверить операцию.",
            },
        )
        assert review.status_code == 202, review.text
        assert client.get("/api/public/mock-social-feed").status_code == 501


_TEAM_CODE = re.compile(r"team_[a-z0-9_]+")
