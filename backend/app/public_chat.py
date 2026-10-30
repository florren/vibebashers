"""T-269: отдельный публичный origin. Здесь нет операторских роутеров и SPA fallback."""

from __future__ import annotations

import asyncio
import io
import os
import time
import wave
from collections import deque
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api import personal, stt
from app.api.common import db
from app.errors import install_error_handlers
from app.stt import registry


class PublicBoundary:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = 1_000_000 if scope["path"] == "/api/stt/transcribe" else 32_768
        total = 0

        async def bounded_receive() -> Message:
            nonlocal total
            message = await receive()
            total += len(message.get("body", b""))
            if total > limit:
                raise HTTPException(413, "Слишком большой запрос")
            return message

        async def secured_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend(
                    [
                        (b"x-content-type-options", b"nosniff"),
                        (b"referrer-policy", b"no-referrer"),
                        (b"x-frame-options", b"DENY"),
                        (b"cache-control", b"no-store"),
                        (b"permissions-policy", b"microphone=(self), camera=(), geolocation=()"),
                        (
                            b"content-security-policy",
                            b"default-src 'self'; script-src 'self' blob:; style-src 'self' 'unsafe-inline'; font-src 'self'; img-src 'self' data:; connect-src 'self'; worker-src 'self' blob:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
                        ),
                    ]
                )
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, bounded_receive, secured_send)


def create_public_app(dist: str | None = None) -> FastAPI:
    app = FastAPI(title="Анонимный чат", docs_url=None, redoc_url=None, openapi_url=None)
    install_error_handlers(app)
    app.add_middleware(PublicBoundary)
    app.include_router(personal.router)
    voice_lock = asyncio.Semaphore(1)
    voice_hits: deque[float] = deque(maxlen=20)

    @app.get("/api/stt/providers", include_in_schema=False)
    async def voice_providers() -> Any:
        # Публичная диктовка использует только локальный Vosk; настройки провайдеров не публикуются.
        p = registry.providers()["vosk"]
        return [p.info(is_default=True).__dict__]

    @app.post("/api/stt/transcribe", include_in_schema=False)
    async def voice_transcribe(request: Request) -> Any:
        personal.same_origin(request)
        async with db() as conn:
            await personal.session(conn, request)
        now = time.monotonic()
        while voice_hits and now - voice_hits[0] > 60:
            voice_hits.popleft()
        if len(voice_hits) >= 10 or voice_lock.locked():
            raise HTTPException(429, "Распознавание занято, повторите немного позже", headers={"Retry-After": "5"})
        voice_hits.append(now)
        async with voice_lock:
            body = await request.body()
            if body[:4] == b"RIFF":
                try:
                    with wave.open(io.BytesIO(body), "rb") as audio:
                        if (
                            audio.getnchannels() != 1
                            or audio.getsampwidth() != 2
                            or audio.getframerate() != 16000
                            or audio.getnframes() > 480000
                        ):
                            raise HTTPException(422, "Нужно WAV mono PCM16 16 кГц, до 30 секунд")
                except (wave.Error, EOFError) as exc:
                    raise HTTPException(422, "Не удалось прочитать WAV") from exc
            elif not body or len(body) % 2 or len(body) > 960000:
                raise HTTPException(422, "Нужно PCM16 16 кГц, до 30 секунд")
            return await stt.post_stt_transcribe(request, provider="vosk", sample_rate=16000)

    root = Path(dist or os.environ.get("PERSONAL_FRONTEND_DIST", "../frontend/dist-personal"))
    if (root / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=root / "assets"), name="personal-assets")
    if (root / "fonts").is_dir():
        app.mount("/fonts", StaticFiles(directory=root / "fonts"), name="personal-fonts")

    @app.get("/", include_in_schema=False)
    async def index() -> Any:
        if not (root / "personal.html").is_file():
            raise HTTPException(503, "Пользовательский интерфейс ещё не собран")
        return FileResponse(root / "personal.html")

    return app


app = create_public_app()
