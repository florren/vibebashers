"""Readiness внутреннего Telegram транспорта; без сети и DB."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit


@dataclass(frozen=True)
class TransportConfiguration:
    bot_id: int
    token: str = field(repr=False)
    secret: bytes = field(repr=False)
    app_secret: str = field(repr=False)
    public_origin: str


def configured(settings: Any) -> TransportConfiguration | None:
    if not settings.tgbot_enabled:
        return None
    token = (settings.telegram_bot_token or "").strip()
    secret = (settings.tgbot_internal_secret or "").encode()
    origin = (settings.tgbot_public_base_url or "").strip().rstrip("/")
    match = re.fullmatch(r"([1-9][0-9]{0,18}):[A-Za-z0-9_-]{20,200}", token)
    try:
        url = urlsplit(origin)
        valid_origin = (
            url.scheme in {"http", "https"}
            and bool(url.hostname)
            and url.path == ""
            and url.username is None
            and url.password is None
            and not url.query
            and not url.fragment
            and url.port != 0
        )
    except ValueError:
        valid_origin = False
    if (
        match is None
        or int(match[1]) > 2**63 - 1
        or len(secret) < 32
        or len(settings.app_secret.encode()) < 32
        or not valid_origin
    ):
        raise ValueError("telegram_transport_not_configured")
    return TransportConfiguration(int(match[1]), token, secret, settings.app_secret, origin)
