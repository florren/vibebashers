"""Одна чистая граница secrets перед console/JSONL и хранением HTTP diagnostics.

Не читает env/ключи, не сохраняет исходные значения и не меняет caller payload.
Это маскирование названных credentials, не произвольного unlabeled текста/ПДн.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

import structlog

REDACTED = "[REDACTED]"
SECRET_FIELDS = frozenset(
    {
        "authorization",
        "proxy_authorization",
        "api_key",
        "apikey",
        "x_api_key",
        "access_token",
        "refresh_token",
        "client_secret",
        "password",
        "secret",
        "encrypted_key",
        "key_enc",
        "app_secret",
        "openrouter_api_key",
        "local_llm_api_key",
        "gigachat_auth_key_1",
        "gigachat_auth_key_2",
        "tracking_token",
    }
)
_LABELS = "|".join(re.escape(label).replace("_", "[_-]") for label in sorted(SECRET_FIELDS, key=len, reverse=True))
_NAMED_SECRET = re.compile(
    rf"""(?P<prefix>(?<![\w-])(?:\\?["'])?(?:{_LABELS})(?:\\?["'])?\s*[:=]\s*)"""
    r"""(?P<value>\\["'](?:\\.|[^\\])*?(?:\\["']|\\?$)|"(?:\\.|[^"\\])*(?:\\)?(?:"|$)|'(?:\\.|[^'\\])*(?:\\)?(?:'|$)|(?:Bearer|Basic)\s+\[REDACTED\]|(?:Bearer|Basic)\s+[^\s,;&{}\[\]<>"']+|[^\s,;&{}\[\]<>"']+)""",
    re.IGNORECASE,
)
_AUTH_SCHEME = re.compile(r"\b(Bearer|Basic)\s+([A-Za-z0-9._~+/=-]+)", re.IGNORECASE)
_TRACKING_URL = re.compile(r"((?:/api/public)?/track/)[^?\s]+(?:\?[^\s]*)?")


def redact_tracking_urls(value: str) -> str:
    """Та же защита capability URL, что существовала в Uvicorn access filter T119."""
    return _TRACKING_URL.sub(r"\1{token}", value)


def redact_text(value: str) -> str:
    def named(match: re.Match[str]) -> str:
        raw = match["value"]
        quote = raw[:2] if raw[:2] in ('\\"', "\\'") else raw[0] if raw[0] in ("'", '"') else ""
        return match["prefix"] + quote + REDACTED + quote

    return _AUTH_SCHEME.sub(
        lambda match: match[1] + " " + REDACTED, _NAMED_SECRET.sub(named, redact_tracking_urls(value))
    )


def _secret_field(key: object) -> bool:
    return isinstance(key, str) and key.casefold().replace("-", "_") in SECRET_FIELDS


def redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: REDACTED if _secret_field(key) else redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact(item) for item in value)
    if isinstance(value, str):
        return redact_text(value)
    return value


def redact_event(logger: Any, method: str, event: structlog.types.EventDict) -> structlog.types.EventDict:
    return {key: REDACTED if _secret_field(key) else redact(value) for key, value in event.items()}
