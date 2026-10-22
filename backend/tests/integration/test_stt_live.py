"""B10: живая сессия /ws/audio — PCM16 из тестового WAV → Vosk → реплики → детектор → отчёт. Пропускается без модели Vosk."""

from __future__ import annotations

import json
import os
import wave
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app
from app.stt.vosk_provider import resolve_model_path

SAMPLE = Path(__file__).resolve().parents[3] / "data" / "stt" / "sample_ru_16k.wav"


@pytest.mark.integration
def test_stt_providers_and_mic_session(seeded: str) -> None:
    os.environ["DATABASE_URL"] = seeded
    os.environ["APP_ENV"] = "test"
    get_settings.cache_clear()
    try:
        _run(seeded)
    finally:
        get_settings.cache_clear()


def _run(dsn: str) -> None:
    has_model = resolve_model_path(None) is not None
    with TestClient(create_app()) as c:
        provs = {p["code"]: p for p in c.get("/api/stt/providers").json()}
        assert provs["browser"]["available"] and provs["browser"]["external_service"]
        assert provs["vosk"]["available"] is has_model
        assert c.post("/api/stt/test", json={"provider": "browser"}).json()["ok"] is True
        assert c.post("/api/stt/test", json={"provider": "salutespeech"}).status_code == 422

        emp = c.get("/api/compliance/branches").json()[0]["employees"][0]
        assert (
            c.post(
                "/api/compliance/sessions",
                json={
                    "employee_id": emp["id"],
                    "source": "mic",
                    "diarization_mode": "stereo",
                    "stt_provider": "browser",
                },
            ).status_code
            == 422
        )

        # browser-провайдер: реплики текстом
        s = c.post(
            "/api/compliance/sessions",
            json={"employee_id": emp["id"], "source": "mic", "diarization_mode": "manual", "stt_provider": "browser"},
        )
        assert s.status_code == 201, s.text
        d = s.json()
        assert d["audio_ws_url"] == f"/ws/audio/{d['id']}" and d["stt_provider"] == "browser"
        with c.websocket_connect(d["audio_ws_url"]) as ws:
            ws.send_text(json.dumps({"type": "hello", "provider": "browser", "speaker": "employee"}))
            assert ws.receive_json()["type"] == "ready"
            ws.send_text(json.dumps({"type": "text", "text": "страховка это формальность", "is_final": False}))
            assert ws.receive_json()["type"] == "partial"
            ws.send_text(
                json.dumps(
                    {
                        "type": "text",
                        "text": "Страховка здесь просто формальность, без неё кредит не одобрят",
                        "is_final": True,
                    }
                )
            )
            m = ws.receive_json()
            assert (
                m["type"] == "final"
                and m["utterance"]["speaker"] == "employee"
                and m["utterance"]["speaker_source"] == "manual"
            )
            ws.send_text(json.dumps({"type": "speaker", "speaker": "client"}))
            ws.send_text(json.dumps({"type": "text", "text": "А мне она нужна?", "is_final": True}))
            m = ws.receive_json()
            assert m["utterance"]["speaker"] == "client" and m["utterance"]["seq"] == 2
            ws.send_text(json.dumps({"type": "end"}))
            closed = ws.receive_json()
            assert closed["type"] == "closed" and "findings" in closed["report"]
        det = c.get(f"/api/compliance/sessions/{d['id']}").json()
        assert det["status"] == "closed" and len(det["utterances"]) == 2

        if not has_model:
            pytest.skip("модель Vosk не установлена (make stt-model)")
        t = c.post("/api/stt/test", json={"provider": "vosk"}).json()
        assert t["ok"] and t["wer"] <= 0.3, t

        s = c.post(
            "/api/compliance/sessions", json={"employee_id": emp["id"], "source": "mic", "diarization_mode": "auto"}
        ).json()
        assert s["stt_provider"] == "vosk"
        with wave.open(str(SAMPLE), "rb") as w:
            pcm = w.readframes(w.getnframes())
        with c.websocket_connect(s["audio_ws_url"]) as ws:
            ws.send_text(json.dumps({"type": "hello", "provider": "vosk", "sample_rate": 16000, "channels": 1}))
            assert ws.receive_json()["model"]
            for i in range(0, len(pcm), 6400):
                ws.send_bytes(pcm[i : i + 6400])
            ws.send_bytes(b"\x00" * 32000)
            ws.send_text(json.dumps({"type": "end"}))
            finals: list[dict] = []
            while True:
                m = ws.receive_json()
                if m["type"] == "final":
                    finals.append(m)
                if m["type"] == "closed":
                    break
        text = " ".join(f["text"] for f in finals)
        assert "комисси" in text and all(f["utterance"]["speaker"] in ("employee", "client") for f in finals)
    with psycopg.connect(dsn.replace("postgresql+psycopg://", "postgresql://")) as conn:
        n = conn.execute("select count(*) from stt_metrics where session_id = %s", (s["id"],)).fetchone()
        assert n and n[0] >= 1
