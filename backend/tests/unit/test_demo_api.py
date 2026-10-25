"""T-194: /api/demo/status|failover и /api/cassettes без живого LLM."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app


def test_cassettes_and_record_toggle() -> None:
    with TestClient(create_app()) as client:
        listed = client.get("/api/cassettes")
        assert listed.status_code == 200
        assert isinstance(listed.json(), list)
        on = client.post("/api/cassettes/record", json={"enabled": True, "scenario_id": "qr_fee_public_review"})
        assert on.status_code == 200
        assert on.json()["enabled"] is True
        status = client.get("/api/demo/status")
        assert status.status_code == 200
        body = status.json()
        assert body["recording_cassettes"] is True
        assert body["llm_mode"] in ("live", "replay", "mock")
        off = client.post("/api/cassettes/record", json={"enabled": False})
        assert off.status_code == 200
        assert client.get("/api/demo/status").json()["recording_cassettes"] is False


def test_failover_replay_changes_mode() -> None:
    with TestClient(create_app()) as client:
        res = client.post("/api/demo/failover", json={"component": "llm", "to": "replay"})
        assert res.status_code == 200
        assert res.json()["llm_mode"] == "replay"
        assert res.json()["badge_ru"] == "офлайн-кассета"
        stt = client.post("/api/demo/failover", json={"component": "stt", "to": "file"})
        assert stt.status_code == 200
        assert stt.json()["stt_mode"] == "file"
