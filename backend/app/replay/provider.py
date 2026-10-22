"""Провайдер replay: воспроизводит кассеты с исходными задержками; промах → ProviderError('miss') → следующий в цепочке."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Any

from app.llm.base import LLMProfile, Message, ProviderError, Usage
from app.replay.store import CassetteStore


class ReplayProvider:
    name = "replay"

    def __init__(
        self,
        store: CassetteStore,
        *,
        source_providers: tuple[str, ...] = ("gigachat", "openai_compatible"),
        speed: float = 1.0,
    ) -> None:
        self.store = store
        self.source_providers = source_providers
        self.speed = speed  # >1 — быстрее исходных задержек

    def _find(self, messages: list[Message], schema: dict[str, Any] | None, profile: LLMProfile) -> dict[str, Any]:
        for prov in (profile.provider, *self.source_providers):
            rec = self.store.get(prov, profile.model, messages, schema)
            if rec:
                return rec
        raise ProviderError("miss", f"нет кассеты для {profile.provider}/{profile.model}")

    async def complete_structured(
        self, messages: list[Message], schema: dict[str, Any], profile: LLMProfile, *, timeout_s: float
    ) -> tuple[dict[str, Any], Usage, str]:
        t0 = time.perf_counter()
        rec = self._find(messages, schema, profile)
        orig_ms = int(rec.get("usage", {}).get("latency_ms", 0))
        delay = min(orig_ms / 1000.0 / max(self.speed, 0.01), timeout_s * 0.8) if orig_ms else 0.0
        if delay:
            await asyncio.sleep(delay)
        resp = rec["response"]
        obj = resp if isinstance(resp, dict) else {}
        u = rec.get("usage", {})
        usage = Usage(
            prompt_tokens=int(u.get("prompt_tokens", 0)),
            completion_tokens=int(u.get("completion_tokens", 0)),
            latency_ms=int((time.perf_counter() - t0) * 1000),
            provider=self.name,
            model=rec["model"],
            source="replay",
        )
        return obj, usage, resp if isinstance(resp, str) else __import__("json").dumps(resp, ensure_ascii=False)

    async def stream(self, messages: list[Message], profile: LLMProfile, *, timeout_s: float) -> AsyncIterator[str]:
        rec = self._find(messages, None, profile)
        prev = 0
        for ch in rec.get("chunks") or [{"delta": str(rec["response"]), "at_ms": 0}]:
            at = int(ch.get("at_ms", 0))
            if at > prev:
                await asyncio.sleep((at - prev) / 1000.0 / max(self.speed, 0.01))
                prev = at
            yield str(ch.get("delta", ""))
