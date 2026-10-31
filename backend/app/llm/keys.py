"""Пул ключей GigaChat (AGENTS §6.3): выбор ключа с наибольшим остатком tokens_limit − tokens_used; 429/квота → следующий."""

from __future__ import annotations

import datetime as dt
import time
from dataclasses import dataclass, field

from app.llm.base import ProviderError
from app.logging import get_logger

log = get_logger(__name__)
DEFAULT_LIMIT = 50_000_000  # GigaChat freemium: 50 млн токенов на ключ


@dataclass
class ApiKey:
    label: str
    secret: str
    provider: str = "gigachat"
    tokens_used: int = 0
    tokens_limit: int | None = DEFAULT_LIMIT
    requests_today: int = 0
    requests_day: dt.date = field(default_factory=lambda: dt.datetime.now(dt.UTC).date())
    is_active: bool = True
    last_error: str | None = None
    cooldown_until: float = 0.0  # monotonic; после 429 ключ временно не выбирается
    db_id: int | None = None
    # кэш access token (GigaChat OAuth)
    access_token: str | None = None
    token_expires_at: float = 0.0

    @property
    def remaining(self) -> int:
        return (self.tokens_limit if self.tokens_limit is not None else 10**12) - self.tokens_used

    def available(self) -> bool:
        return self.is_active and self.remaining > 0 and time.monotonic() >= self.cooldown_until


class KeyPool:
    def __init__(self, keys: list[ApiKey] | None = None) -> None:
        self.keys: list[ApiKey] = keys or []

    @classmethod
    def from_env(cls, *values: str | None, provider: str = "gigachat") -> KeyPool:
        keys = [ApiKey(label=f"{provider}_env_{i + 1}", secret=v, provider=provider) for i, v in enumerate(values) if v]
        return cls(keys)

    def __len__(self) -> int:
        return len(self.keys)

    def pick(self, exclude: set[str] | None = None) -> ApiKey:
        cands = [k for k in self.keys if k.available() and k.label not in (exclude or set())]
        if not cands:
            active = [k for k in self.keys if k.is_active and k.label not in (exclude or set())]
            cooling = [k for k in active if k.remaining > 0]
            # Транспортная пауза мягкая: если других ключей нет, пробуем самый
            # давно отказавший. 429/auth/quota по-прежнему не обходятся.
            transient = [k for k in cooling if (k.last_error or "").startswith(("timeout:", "network:"))]
            if transient:
                return min(transient, key=lambda k: k.cooldown_until)
            if cooling and len(cooling) == len(active):
                wait = max(0.0, min(k.cooldown_until for k in cooling) - time.monotonic())
                raise ProviderError("rate_limit", "ключи временно на паузе после 429", retry_after_s=wait)
            raise ProviderError("quota", "нет доступных ключей (все исчерпаны, неактивны или на паузе после 429)")
        return max(cands, key=lambda k: k.remaining)

    def add_usage(self, key: ApiKey, tokens: int) -> None:
        today = dt.datetime.now(dt.UTC).date()
        if key.requests_day != today:
            key.requests_day, key.requests_today = today, 0
        key.tokens_used += tokens
        key.requests_today += 1
        if not (key.cooldown_until > time.monotonic() and (key.last_error or "").startswith("rate_limit:")):
            key.last_error = None
            key.cooldown_until = 0.0

    def mark_error(self, key: ApiKey, err: ProviderError) -> None:
        if (
            err.kind in ("timeout", "network")
            and key.cooldown_until > time.monotonic()
            and (key.last_error or "").startswith("rate_limit:")
        ):
            # Отмена другого запроса не должна сокращать уже полученный Retry-After.
            return
        key.last_error = f"{err.kind}: {err.detail[:200]}"
        if err.kind == "rate_limit":
            key.cooldown_until = time.monotonic() + (err.retry_after_s or 20.0)
        elif err.kind in ("timeout", "network"):
            # Короткая пауза не списывает квоту и не деактивирует рабочий ключ.
            # Нужна и после внешней отмены: резервная модель должна сменить ключ.
            key.cooldown_until = time.monotonic() + 10.0
        elif err.kind == "quota":
            key.tokens_used = key.tokens_limit or key.tokens_used
        elif err.kind == "auth":
            key.is_active = False
            key.access_token = None
        log.warning("llm_key_error", key=key.label, kind=err.kind, detail=err.detail[:120])

    def snapshot(self) -> list[dict[str, object]]:
        return [
            {
                "label": k.label,
                "provider": k.provider,
                "tokens_used": k.tokens_used,
                "tokens_limit": k.tokens_limit,
                "requests_today": k.requests_today,
                "is_active": k.is_active,
                "last_error": k.last_error,
                "available": k.available(),
            }
            for k in self.keys
        ]
