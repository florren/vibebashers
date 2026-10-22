"""Rate limiter per profile (AGENTS §6.3): token bucket (rpm) в памяти + суточный счётчик (rpd)."""

from __future__ import annotations

import asyncio
import datetime as dt
import time
from dataclasses import dataclass, field

from app.llm.base import ProviderError


@dataclass
class _Bucket:
    rpm: int | None
    rpd: int | None
    tokens: float = 0.0
    updated: float = field(default_factory=time.monotonic)
    day: dt.date = field(default_factory=lambda: dt.datetime.now(dt.UTC).date())
    today: int = 0

    def __post_init__(self) -> None:
        self.tokens = float(self.rpm or 0)


class RateLimiter:
    def __init__(self, max_wait_s: float = 5.0) -> None:
        self._b: dict[str, _Bucket] = {}
        self._lock = asyncio.Lock()
        self.max_wait_s = max_wait_s

    def configure(self, code: str, rpm: int | None, rpd: int | None) -> None:
        if code not in self._b or (self._b[code].rpm, self._b[code].rpd) != (rpm, rpd):
            self._b[code] = _Bucket(rpm, rpd)

    async def acquire(self, code: str, rpm: int | None = None, rpd: int | None = None) -> None:
        """Ждёт слот не дольше max_wait_s; при исчерпании суточного лимита — ProviderError('rate_limit')."""
        async with self._lock:
            self.configure(code, rpm, rpd)
            b = self._b[code]
            today = dt.datetime.now(dt.UTC).date()
            if b.day != today:
                b.day, b.today = today, 0
            if b.rpd is not None and b.today >= b.rpd:
                raise ProviderError(
                    "rate_limit", f"суточный лимит {b.rpd} запросов исчерпан для {code}", retry_after_s=3600
                )
            if b.rpm:
                now = time.monotonic()
                b.tokens = min(float(b.rpm), b.tokens + (now - b.updated) * b.rpm / 60.0)
                b.updated = now
                if b.tokens < 1:
                    wait = (1 - b.tokens) * 60.0 / b.rpm
                    if wait > self.max_wait_s:
                        raise ProviderError(
                            "rate_limit", f"лимит {b.rpm} rpm для {code}: ждать {wait:.1f} с", retry_after_s=wait
                        )
                    await asyncio.sleep(wait)
                    b.tokens = 1.0
                    b.updated = time.monotonic()
                b.tokens -= 1
            b.today += 1

    def stats(self) -> dict[str, dict[str, float | int | None]]:
        return {
            c: {"rpm": b.rpm, "rpd": b.rpd, "today": b.today, "tokens": round(b.tokens, 2)} for c, b in self._b.items()
        }


limiter = RateLimiter()
