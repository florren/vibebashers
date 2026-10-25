"""T-183: source=file читает WAV чанками в LiveSession. STT подменяется, Vosk не обязателен."""

from __future__ import annotations

import os
import threading
import time
import wave
from pathlib import Path
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

import app.stt.live as live_mod
import app.stt.registry as registry_mod
from app.config import get_settings
from app.main import create_app
from app.stt.base import STTResult
from app.stt.vosk_provider import resolve_model_path

ROOT = Path(__file__).resolve().parents[3]
SAMPLE = ROOT / "data" / "stt" / "sample_ru_16k.wav"


class _Gate:
    def __init__(self, texts: list[str], pause_at: int | None) -> None:
        self.texts = texts
        self.pause_at = pause_at
        self.feeds = 0
        self.lock = threading.Lock()
        self.reached = threading.Event()
        self.release = threading.Event()
        self.finished = threading.Event()


class _Stream:
    def __init__(self, gate: _Gate) -> None:
        self.gate = gate

    def feed(self, pcm: bytes) -> list[STTResult]:
        with self.gate.lock:
            self.gate.feeds += 1
            n = self.gate.feeds
        if self.gate.pause_at == n:
            self.gate.reached.set()
            self.gate.release.wait(10)
        if n > len(self.gate.texts):
            return []
        text = self.gate.texts[n - 1]
        return [STTResult("partial", text), STTResult("final", text)]

    def finish(self) -> None:
        self.gate.finished.set()
        return None


class _Info:
    model: str | None = "fake-stt"


class _Provider:
    code = "vosk"

    def __init__(self, box: dict[str, _Gate]) -> None:
        self.box = box

    def info(self, is_default: bool = False) -> _Info:
        return _Info()

    def open_stream(self, sample_rate: int) -> _Stream:
        return _Stream(self.box["gate"])


def _dsn(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def _write_wav(path: Path, channels: int, frames: int, *, rate: int = 16000, width: int = 2) -> None:
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(width)
        wf.setframerate(rate)
        wf.writeframes(b"\x00" * frames * channels * width)


def _insert_asset(dsn: str, kind: str, path: str) -> int:
    with psycopg.connect(_dsn(dsn), autocommit=True) as conn:
        row = conn.execute(
            "insert into demo_assets (kind, title_ru, path, checksum, duration_ms) values (%s, %s, %s, %s, %s) returning id",
            (kind, "Тестовая запись", path, "0" * 64, 200),
        ).fetchone()
    assert row is not None
    return int(row[0])


def _files(root: Path) -> set[Path]:
    return {p.resolve() for p in root.rglob("*") if p.is_file()}


def _wait_closed(client: TestClient, session_id: int, gate: _Gate, timeout: float = 15.0) -> dict[str, Any]:
    assert gate.finished.wait(timeout), "проигрыватель не завершился"
    deadline = time.monotonic() + timeout
    detail: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        detail = client.get(f"/api/compliance/sessions/{session_id}").json()
        if detail["status"] == "closed":
            return detail
        time.sleep(0.02)
    raise AssertionError(detail["status"] if detail else "нет сессии")


def _report_source(dsn: str, session_id: int) -> str | None:
    with psycopg.connect(_dsn(dsn), autocommit=True) as conn:
        row = conn.execute("select report->>'source' from audio_sessions where id = %s", (session_id,)).fetchone()
    assert row is not None
    return None if row[0] is None else str(row[0])


@pytest.mark.integration
def test_file_audio_session(seeded: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    os.environ["DATABASE_URL"] = seeded
    os.environ["APP_ENV"] = "test"
    get_settings.cache_clear()
    box: dict[str, _Gate] = {"gate": _Gate(["ожидание"], None)}
    provider = _Provider(box)

    def fake_get(code: str | None) -> _Provider:
        if code in (None, "vosk"):
            return provider
        raise LookupError(str(code))

    monkeypatch.setattr(registry_mod, "get", fake_get)
    monkeypatch.setattr(live_mod.registry, "get", fake_get)
    try:
        _run(seeded, tmp_path, box)
    finally:
        get_settings.cache_clear()


def _run(dsn: str, tmp_path: Path, box: dict[str, _Gate]) -> None:
    with TestClient(create_app()) as client:
        emp = client.get("/api/compliance/branches").json()[0]["employees"][0]
        base = {"employee_id": emp["id"], "diarization_mode": "manual", "stt_provider": "vosk", "store_audio": False}

        assert client.post("/api/compliance/sessions", json={**base, "source": "tape"}).status_code == 422
        assert client.post("/api/compliance/sessions", json={**base, "source": "file"}).status_code == 422
        missing = client.post("/api/compliance/sessions", json={**base, "source": "file", "demo_asset_id": 9_999_999})
        assert missing.status_code == 404
        post_id = _insert_asset(dsn, "post", str(tmp_path / "absent.wav"))
        assert (
            client.post(
                "/api/compliance/sessions", json={**base, "source": "file", "demo_asset_id": post_id}
            ).status_code
            == 422
        )
        bad = tmp_path / "bad_rate.wav"
        _write_wav(bad, 1, 1600, rate=8000)
        bad_id = _insert_asset(dsn, "audio", str(bad))
        assert (
            client.post(
                "/api/compliance/sessions", json={**base, "source": "file", "demo_asset_id": bad_id}
            ).status_code
            == 422
        )
        narrow = tmp_path / "narrow.wav"
        _write_wav(narrow, 1, 1600, width=1)
        narrow_id = _insert_asset(dsn, "audio", str(narrow))
        assert (
            client.post(
                "/api/compliance/sessions", json={**base, "source": "file", "demo_asset_id": narrow_id}
            ).status_code
            == 422
        )
        mono = tmp_path / "mono.wav"
        _write_wav(mono, 1, 1600)
        mono_id = _insert_asset(dsn, "audio", str(mono))
        stereo_req = {**base, "source": "file", "demo_asset_id": mono_id, "diarization_mode": "stereo"}
        assert client.post("/api/compliance/sessions", json=stereo_req).status_code == 422
        browser = {**base, "source": "file", "demo_asset_id": mono_id, "stt_provider": "browser"}
        assert client.post("/api/compliance/sessions", json=browser).status_code == 422
        alien = {**base, "source": "file", "demo_asset_id": mono_id, "stt_provider": "salutespeech"}
        assert client.post("/api/compliance/sessions", json=alien).status_code == 422
        gone = {**base, "employee_id": 9_999_999, "source": "file", "demo_asset_id": mono_id}
        assert client.post("/api/compliance/sessions", json=gone).status_code == 404
        mode = {**base, "source": "file", "demo_asset_id": mono_id, "diarization_mode": "none"}
        assert client.post("/api/compliance/sessions", json=mode).status_code == 422

        manual_wav = tmp_path / "manual.wav"
        _write_wav(manual_wav, 1, 3200)
        manual_id = _insert_asset(dsn, "audio", str(manual_wav))
        manual_gate = _Gate(["добрый день", "да, слушаю"], pause_at=2)
        box["gate"] = manual_gate
        before = _files(tmp_path)
        created = client.post(
            "/api/compliance/sessions",
            json={**base, "source": "file", "demo_asset_id": manual_id, "diarization_mode": "manual"},
        )
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["audio_ws_url"] is None and body["sample_rate"] == 16000 and body["channels"] == 1
        assert body["source"] == "file" and body["pacing"] == "realtime" and body["store_audio"] is False
        sid = int(body["id"])
        try:
            assert manual_gate.reached.wait(5), "нет паузы фейка на втором чанке"
            live = client.get(f"/api/compliance/sessions/{sid}").json()
            assert len(live["utterances"]) == 1
            assert live["utterances"][0]["speaker"] == "employee"
            assert live["utterances"][0]["speaker_source"] == "manual"
            first_id = live["utterances"][0]["id"]
            role = client.post(f"/api/compliance/sessions/{sid}/role", json={"speaker": "client"})
            assert role.status_code == 204
            again = client.get(f"/api/compliance/sessions/{sid}").json()
            assert again["utterances"][0]["id"] == first_id and again["utterances"][0]["speaker"] == "employee"
        finally:
            manual_gate.release.set()
        done = _wait_closed(client, sid, manual_gate)
        assert _files(tmp_path) == before
        assert [u["speaker"] for u in done["utterances"]] == ["employee", "client"]
        assert [u["speaker_source"] for u in done["utterances"]] == ["manual", "manual"]
        assert [u["text"] for u in done["utterances"]] == ["добрый день", "да, слушаю"]
        assert _report_source(dsn, sid) == "file"

        stereo_wav = tmp_path / "stereo.wav"
        _write_wav(stereo_wav, 2, 1600)
        stereo_id = _insert_asset(dsn, "audio", str(stereo_wav))
        stereo_gate = _Gate(["канал сотрудника", "канал клиента"], pause_at=None)
        box["gate"] = stereo_gate
        stereo = client.post(
            "/api/compliance/sessions",
            json={**base, "source": "file", "demo_asset_id": stereo_id, "diarization_mode": "stereo"},
        )
        assert stereo.status_code == 201, stereo.text
        assert stereo.json()["channels"] == 2 and stereo.json()["audio_ws_url"] is None
        stereo_done = _wait_closed(client, int(stereo.json()["id"]), stereo_gate)
        assert [(u["speaker"], u["speaker_source"]) for u in stereo_done["utterances"]] == [
            ("employee", "channel"),
            ("client", "channel"),
        ]

        auto_wav = tmp_path / "auto.wav"
        _write_wav(auto_wav, 1, 1600)
        auto_rel = os.path.relpath(auto_wav, ROOT)
        auto_id = _insert_asset(dsn, "audio", auto_rel)
        auto_gate = _Gate(["оформите страховка по вкладу"], pause_at=None)
        box["gate"] = auto_gate
        auto = client.post(
            "/api/compliance/sessions",
            json={**base, "source": "file", "demo_asset_id": auto_id, "diarization_mode": "auto"},
        )
        assert auto.status_code == 201, auto.text
        auto_done = _wait_closed(client, int(auto.json()["id"]), auto_gate)
        assert auto_done["utterances"][0]["speaker_source"] == "llm"
        assert auto_done["utterances"][0]["speaker"] == "employee"
        assert auto_done["utterances"][0]["text"] == "оформите страховка по вкладу"

        stop_wav = tmp_path / "stop.wav"
        _write_wav(stop_wav, 1, 16000)
        stop_id = _insert_asset(dsn, "audio", str(stop_wav))
        stop_gate = _Gate([f"кусок {i}" for i in range(10)], pause_at=1)
        box["gate"] = stop_gate
        stopped = client.post(
            "/api/compliance/sessions",
            json={**base, "source": "file", "demo_asset_id": stop_id, "diarization_mode": "manual"},
        )
        assert stopped.status_code == 201, stopped.text
        stop_sid = int(stopped.json()["id"])
        try:
            assert stop_gate.reached.wait(5), "нет паузы фейка"
            stop = client.post(f"/api/compliance/sessions/{stop_sid}/stop")
            assert stop.status_code == 200 and stop.json()["status"] == "closed"
        finally:
            stop_gate.release.set()
        stop_done = _wait_closed(client, stop_sid, stop_gate)
        assert stop_done["status"] == "closed"
        assert stop_gate.feeds == 1
        assert len(stop_done["utterances"]) == 1
        assert _files(tmp_path) == before.union(
            {
                manual_wav.resolve(),
                stereo_wav.resolve(),
                auto_wav.resolve(),
                stop_wav.resolve(),
                bad.resolve(),
                narrow.resolve(),
                mono.resolve(),
            }
        )


@pytest.mark.integration
def test_file_session_vosk_sample(seeded: str) -> None:
    if not SAMPLE.is_file() or resolve_model_path(None) is None:
        pytest.skip("нет data/stt/sample_ru_16k.wav или модели Vosk")
    os.environ["DATABASE_URL"] = seeded
    os.environ["APP_ENV"] = "test"
    get_settings.cache_clear()
    try:
        before = _files(SAMPLE.parent)
        asset_id = _insert_asset(seeded, "audio", str(SAMPLE))
        with TestClient(create_app()) as client:
            emp = client.get("/api/compliance/branches").json()[0]["employees"][0]
            created = client.post(
                "/api/compliance/sessions",
                json={
                    "employee_id": emp["id"],
                    "source": "file",
                    "demo_asset_id": asset_id,
                    "diarization_mode": "manual",
                    "stt_provider": "vosk",
                    "store_audio": False,
                },
            )
            assert created.status_code == 201, created.text
            assert created.json()["audio_ws_url"] is None and created.json()["store_audio"] is False
            sid = int(created.json()["id"])
            deadline = time.monotonic() + 40
            detail: dict[str, Any] | None = None
            while time.monotonic() < deadline:
                detail = client.get(f"/api/compliance/sessions/{sid}").json()
                if detail["status"] == "closed":
                    break
                time.sleep(0.2)
            assert detail is not None and detail["status"] == "closed"
        assert _files(SAMPLE.parent) == before
    finally:
        get_settings.cache_clear()
