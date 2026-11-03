"""Ограниченная ASGI-граница internal inbound до Pydantic и DB handlers."""

from __future__ import annotations

from collections.abc import Callable

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.errors import Problem
from app.tgbot.signature import MAX_BODY_BYTES, BotTransportDisabled, InvalidBotSignature, verify_signature

INBOUND_PATH = "/api/internal/tgbot/inbound"
HEARTBEAT_PATH = "/api/internal/tgbot/heartbeat"


class BotSignatureMiddleware:
    def __init__(self, app: ASGIApp, secret: Callable[[], bytes | None]) -> None:
        self.app, self.secret = app, secret

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] not in {INBOUND_PATH, HEARTBEAT_PATH}:
            await self.app(scope, receive, send)
            return
        secret = self.secret()
        if secret is None or len(secret) < 32:
            await self.reject(scope, receive, send, 503, "telegram_transport_not_configured")
            return
        headers: dict[bytes, list[bytes]] = {}
        for name, value in scope.get("headers", []):
            headers.setdefault(name.lower(), []).append(value)
        try:
            # Два значения одного security header неоднозначны и не нормализуются.
            stamps = headers.get(b"x-cx-tg-timestamp", [])
            signatures = headers.get(b"x-cx-tg-signature", [])
            if len(stamps) != 1 or len(signatures) != 1:
                raise InvalidBotSignature()
            timestamp, signature = stamps[0].decode("ascii"), signatures[0].decode("ascii")
            chunks, size = [], 0
            while True:
                event = await receive()
                if event["type"] == "http.disconnect":
                    return
                chunk = event.get("body", b"")
                size += len(chunk)
                if size > MAX_BODY_BYTES:
                    await self.reject(scope, receive, send, 413, "telegram_update_too_large")
                    return
                chunks.append(chunk)
                if not event.get("more_body", False):
                    break
            body = b"".join(chunks)
            verify_signature(
                secret,
                method=scope["method"],
                path=scope["path"],
                body=body,
                timestamp=timestamp,
                signature=signature,
            )
        except (InvalidBotSignature, UnicodeDecodeError):
            await self.reject(scope, receive, send, 401, "invalid_telegram_transport_signature")
            return
        except BotTransportDisabled:
            await self.reject(scope, receive, send, 503, "telegram_transport_not_configured")
            return
        consumed = False

        async def replay_body() -> Message:
            nonlocal consumed
            if not consumed:
                consumed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay_body, send)

    @staticmethod
    async def reject(scope: Scope, receive: Receive, send: Send, status: int, code: str) -> None:
        await Problem(status, "Telegram transport", code).to_response(scope["path"])(scope, receive, send)
