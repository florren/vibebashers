"""Один bounded Bot API sendMessage; без скрытых retries и raw upstream diagnostics."""

from __future__ import annotations

import json
import logging
import re
from contextvars import ContextVar
from typing import Any, Literal

import httpx

_BOT_REQUEST: ContextVar[bool] = ContextVar("telegram_http_request", default=False)
_SDK_LOGGERS = ("httpx", "httpcore.connection", "httpcore.http11", "httpcore.http2", "httpcore.proxy", "httpcore.socks")


class DeliveryError(Exception):
    def __init__(self, kind: Literal["rejected", "unknown"], code: str) -> None:
        self.kind, self.code = kind, code
        super().__init__(code)


class TelegramHTTPFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if _BOT_REQUEST.get():
            # Token входит в URL; headers/errors могут содержать upstream echo.
            # Scope — только текущий Bot HTTP task, чужие HTTP logs не меняются.
            record.msg, record.args = "telegram_http_transport_event", ()
            record.exc_info, record.exc_text, record.stack_info = None, None, None
        return True


class TelegramClient:
    def __init__(self, token: str, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        if re.fullmatch(r"[1-9][0-9]{0,18}:[A-Za-z0-9_-]{20,200}", token) is None:
            raise ValueError("telegram_token_invalid")
        self._url = f"https://api.telegram.org/bot{token}/sendMessage"
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(10, connect=5), follow_redirects=False, trust_env=False, transport=transport
        )
        self._filter = TelegramHTTPFilter()
        for name in _SDK_LOGGERS:
            logging.getLogger(name).addFilter(self._filter)

    async def aclose(self) -> None:
        scope = _BOT_REQUEST.set(True)
        try:
            await self._http.aclose()
        finally:
            _BOT_REQUEST.reset(scope)
            for name in _SDK_LOGGERS:
                logging.getLogger(name).removeFilter(self._filter)

    async def send(self, payload: dict[str, Any]) -> str:
        chat = payload.get("chat_id")
        text = payload.get("text")
        if (
            type(chat) is not int
            or not 0 < chat <= 2**63 - 1
            or not isinstance(text, str)
            or not 1 <= len(text.encode("utf-16-le")) // 2 <= 4096
            or set(payload) - {"chat_id", "text", "link_preview_options", "reply_markup"}
        ):
            raise DeliveryError("rejected", "telegram_payload_invalid")
        scope = _BOT_REQUEST.set(True)
        try:
            try:
                async with self._http.stream("POST", self._url, json=payload) as response:
                    chunks, size = [], 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > 65536:
                            raise DeliveryError("unknown", "telegram_response_too_large")
                        chunks.append(chunk)
                    status = response.status_code
                data: object = json.loads(b"".join(chunks))
            except (httpx.HTTPError, ValueError):
                raise DeliveryError("unknown", "telegram_transport_unknown") from None
            if not isinstance(data, dict):
                raise DeliveryError("unknown", "telegram_response_invalid")
            if status in {400, 401, 403, 404, 429} and data.get("ok") is False:
                # Явный отказ Bot API, не network timeout и не повод скрытого resend.
                raise DeliveryError("rejected", f"telegram_rejected_{status}")
            result = data.get("result")
            if status != 200 or data.get("ok") is not True or not isinstance(result, dict):
                raise DeliveryError("unknown", "telegram_response_unknown")
            message_id = result.get("message_id")
            target = result.get("chat")
            if (
                type(message_id) is not int
                or message_id <= 0
                or not isinstance(target, dict)
                or type(target.get("id")) is not int
                or target["id"] != chat
            ):
                raise DeliveryError("unknown", "telegram_response_identity_invalid")
            # Не сохраняем result.text/description/headers и произвольный response payload.
            return f"telegram:{message_id}"
        finally:
            _BOT_REQUEST.reset(scope)
