"""Роутер тега `stt` (T-181/T-193): провайдеры распознавания речи и проверка на предзаписанном файле."""

from __future__ import annotations

import asyncio
import wave
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.errors import Problem
from app.stt import registry

router = APIRouter(tags=["stt"])

SAMPLE_WAV = Path(__file__).resolve().parents[3] / "data" / "stt" / "sample_ru_16k.wav"
SAMPLE_TEXT = "здравствуйте у меня списали комиссию за перевод хотя обещали что бесплатно хочу вернуть деньги"


def _sample_path() -> Path | None:
    for c in (SAMPLE_WAV, Path("/data/stt/sample_ru_16k.wav")):
        if c.exists():
            return c
    return None


def wer(ref: str, hyp: str) -> float:
    r, h = ref.split(), hyp.split()
    d = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(h) + 1):
            cur = d[j]
            d[j] = min(d[j] + 1, d[j - 1] + 1, prev + (r[i - 1] != h[j - 1]))
            prev = cur
    return d[len(h)] / max(1, len(r))


@router.get("/api/stt/providers", summary="Доступные STT-провайдеры, их возможности и состояние")
async def get_stt_providers() -> Any:
    return [p.__dict__ for p in registry.list_info()]


class TestBody(BaseModel):
    provider: str | None = None
    demo_asset_id: int | None = None


@router.post("/api/stt/test", summary="Проверка провайдера на коротком предзаписанном файле (мастер, шаг 4)")
async def post_stt_test(body: TestBody) -> Any:
    code = body.provider or registry.default_code()
    if code == "browser":
        return {
            "ok": True,
            "provider": code,
            "text": None,
            "latency_ms": None,
            "wer": None,
            "note_ru": "Проверяется в браузере: Chrome/Edge, доступ к микрофону; аудио на сервер не передаётся",
        }
    try:
        p = registry.get(code)
    except LookupError:
        info = next((x for x in registry.list_info() if x.code == code), None)
        raise Problem(422, f"STT-провайдер {code!r} недоступен", detail=info.note_ru if info else None) from None
    path = _sample_path()
    if path is None:
        raise Problem(500, "Нет тестового файла data/stt/sample_ru_16k.wav")
    with wave.open(str(path), "rb") as w:
        sr, pcm = w.getframerate(), w.readframes(w.getnframes())
    text, ms = await asyncio.to_thread(p.transcribe, pcm, sr)
    return {
        "ok": bool(text),
        "provider": code,
        "model": p.info().model,
        "text": text,
        "expected": SAMPLE_TEXT,
        "wer": round(wer(SAMPLE_TEXT, text), 3),
        "latency_ms": ms,
        "audio_seconds": round(len(pcm) / (2 * sr), 2),
    }


@router.post(
    "/api/stt/transcribe",
    summary="Надиктовать текст: PCM16 LE 16 кГц mono (application/octet-stream) или WAV → текст (T-206)",
)
async def post_stt_transcribe(request: Request, provider: str | None = None, sample_rate: int = 16000) -> Any:
    code = provider or registry.default_code()
    if code == "browser":
        raise Problem(422, "Провайдер browser распознаёт в браузере — на сервер присылайте текст")
    try:
        p = registry.get(code)
    except LookupError:
        raise Problem(422, f"STT-провайдер {code!r} недоступен") from None
    body = await request.body()
    if not body:
        raise Problem(422, "Пустое аудио")
    if body[:4] == b"RIFF":
        import io

        with wave.open(io.BytesIO(body), "rb") as w:
            sample_rate, body = w.getframerate(), w.readframes(w.getnframes())
    if len(body) > 2 * sample_rate * 120:
        raise Problem(413, "Не длиннее 120 секунд")
    text, ms = await asyncio.to_thread(p.transcribe, body, sample_rate)
    return {
        "ok": bool(text),
        "provider": code,
        "text": text,
        "latency_ms": ms,
        "audio_seconds": round(len(body) / (2 * sample_rate), 2),
    }
