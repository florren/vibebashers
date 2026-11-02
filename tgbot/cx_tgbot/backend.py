"""Подписанный transport к backend; тексты upstream ошибок не журналируются."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections.abc import Callable
from typing import Any

import httpx

INBOUND_PATH = "/api/internal/tgbot/inbound"


class BackendUnavailable(Exception):
    def __init__(self, status: int | None = None) -> None:
        self.status = status
        super().__init__("telegram_backend_unavailable")


class BackendClient:
    def __init__(self, http: httpx.AsyncClient, secret: bytes, *, clock: Callable[[], float] = time.time) -> None:
        if len(secret) < 32:
            raise ValueError("telegram_internal_secret_too_short")
        self.http, self.secret = http, secret
        self.clock = clock

    async def submit(self, event: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(event, ensure_ascii=False, separators=(",", ":")).encode()
        if len(body) > 32_768:
            raise ValueError("telegram_update_too_large")
        timestamp = str(int(self.clock()))
        payload = "\n".join(("cx-tgbot-v1", timestamp, "POST", INBOUND_PATH, hashlib.sha256(body).hexdigest())).encode()
        signature = hmac.new(self.secret, payload, hashlib.sha256).hexdigest()
        try:
            response = await self.http.post(
                INBOUND_PATH,
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-CX-Tg-Timestamp": timestamp,
                    "X-CX-Tg-Signature": signature,
                },
            )
        except httpx.HTTPError:
            raise BackendUnavailable() from None
        if response.status_code != 200:
            raise BackendUnavailable(response.status_code)
        try:
            result: object = response.json()
        except ValueError:
            raise BackendUnavailable(200) from None
        if not isinstance(result, dict):
            raise BackendUnavailable(200)
        return result
