"""T-121: проверка подписи точного тела до открытия DB-транзакции."""

from __future__ import annotations

import hashlib
import hmac
import math
import re
import time

MAX_BODY_BYTES = 32_768
TIMESTAMP_WINDOW_S = 60


class BotTransportDisabled(ValueError):
    def __init__(self) -> None:
        super().__init__("telegram_transport_not_configured")


class InvalidBotSignature(ValueError):
    def __init__(self) -> None:
        super().__init__("invalid_telegram_transport_signature")


def verify_signature(
    secret: bytes | None,
    *,
    method: str,
    path: str,
    body: bytes,
    timestamp: str | None,
    signature: str | None,
    now: float | None = None,
) -> None:
    """Без нормализации JSON: подпись относится к переданным bytes, method и path.

    Окно timestamp ограничивает повтор HTTP; durable Telegram update_id отдельно
    обеспечивает идемпотентность обработки. Проверка не записывает counters/state.
    """
    if secret is None or len(secret) < 32:
        raise BotTransportDisabled()
    if (
        len(body) > MAX_BODY_BYTES
        or timestamp is None
        or re.fullmatch(r"[0-9]{1,12}", timestamp) is None
        or signature is None
        or re.fullmatch(r"[0-9a-f]{64}", signature) is None
    ):
        raise InvalidBotSignature()
    current = time.time() if now is None else now
    if not math.isfinite(current) or abs(current - int(timestamp)) > TIMESTAMP_WINDOW_S:
        raise InvalidBotSignature()
    payload = "\n".join(("cx-tgbot-v1", timestamp, method.upper(), path, hashlib.sha256(body).hexdigest())).encode()
    expected = hmac.new(secret, payload, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise InvalidBotSignature()
