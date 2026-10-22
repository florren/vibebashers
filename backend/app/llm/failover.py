"""Цепочка провайдеров с failover (AGENTS §6.3): таймауты по контексту, любая ошибка → следующий → mock; симуляция не останавливается.

Запись кассет при LLM_RECORD=1 (успешный ответ live-провайдера → CassetteStore)."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from app.llm.base import TIMEOUTS_S, Context, LLMProfile, Message, Provider, ProviderError, Usage
from app.llm.mock import MockProvider
from app.llm.ratelimit import RateLimiter
from app.llm.ratelimit import limiter as default_limiter
from app.logging import get_logger
from app.replay.store import CassetteStore

log = get_logger(__name__)


@dataclass
class Attempt:
    provider: str
    ok: bool
    ms: int
    error: str | None = None


@dataclass
class ChainResult:
    obj: dict[str, Any]
    usage: Usage
    raw: str
    provider: str
    attempts: list[Attempt] = field(default_factory=list)

    @property
    def fallback_mock(self) -> bool:
        return self.provider == "mock" and any(a.provider != "mock" for a in self.attempts)

    @property
    def error(self) -> str | None:
        errs = [f"{a.provider}: {a.error}" for a in self.attempts if not a.ok]
        return "; ".join(errs) or None


class ProviderChain:
    def __init__(
        self,
        providers: list[Provider],
        *,
        record_store: CassetteStore | None = None,
        rate_limiter: RateLimiter | None = None,
        timeouts: dict[str, float] | None = None,
    ) -> None:
        if not providers or providers[-1].name != "mock":
            providers = [*providers, MockProvider()]  # mock всегда замыкает цепочку
        self.providers = providers
        self.record_store = record_store
        self.limiter = rate_limiter or default_limiter
        self.timeouts = {**TIMEOUTS_S, **(timeouts or {})}

    @property
    def names(self) -> list[str]:
        return [p.name for p in self.providers]

    def timeout_for(self, context: Context | str) -> float:
        return self.timeouts.get(context, self.timeouts["default"])

    async def complete_structured(
        self,
        messages: list[Message],
        schema: dict[str, Any],
        profile: LLMProfile,
        *,
        context: Context | str = "default",
    ) -> ChainResult:
        timeout_s = self.timeout_for(context)
        attempts: list[Attempt] = []
        for prov in self.providers:
            t0 = time.perf_counter()
            try:
                if prov.name not in ("mock", "replay"):
                    await self.limiter.acquire(profile.code, profile.rpm_limit, profile.rpd_limit)
                obj, usage, raw = await asyncio.wait_for(
                    prov.complete_structured(messages, schema, profile, timeout_s=timeout_s), timeout=timeout_s
                )
            except TimeoutError:
                ms = int((time.perf_counter() - t0) * 1000)
                attempts.append(Attempt(prov.name, False, ms, f"timeout {timeout_s:.0f}s ({context})"))
                log.warning("llm_timeout", provider=prov.name, context=context, ms=ms)
                continue
            except ProviderError as e:
                ms = int((time.perf_counter() - t0) * 1000)
                attempts.append(Attempt(prov.name, False, ms, f"{e.kind}: {e.detail[:160]}"))
                (log.info if e.kind == "miss" else log.warning)(
                    "llm_provider_error", provider=prov.name, kind=e.kind, ms=ms
                )
                continue
            except Exception as e:  # любая иная ошибка — тоже failover, но с полным логом
                ms = int((time.perf_counter() - t0) * 1000)
                attempts.append(Attempt(prov.name, False, ms, f"{type(e).__name__}: {str(e)[:160]}"))
                log.exception("llm_provider_crash", provider=prov.name)
                continue
            ms = int((time.perf_counter() - t0) * 1000)
            attempts.append(Attempt(prov.name, True, ms))
            if self.record_store is not None and usage.source == "live":
                self.record_store.record(
                    prov.name, profile.model, messages, schema, response=obj, usage=usage.as_dict()
                )
            if attempts and any(not a.ok for a in attempts):
                log.info("llm_failover", used=prov.name, failed=[a.provider for a in attempts if not a.ok])
            return ChainResult(obj, usage, raw, prov.name, attempts)
        raise RuntimeError("цепочка провайдеров пуста — недостижимо, mock замыкает цепочку")

    async def stream(
        self, messages: list[Message], profile: LLMProfile, *, context: Context | str = "default"
    ) -> AsyncIterator[str]:
        """Поток токенов: первый провайдер, отдавший хотя бы один чанк, становится источником; ошибка до первого чанка → следующий."""
        timeout_s = self.timeout_for(context)
        for prov in self.providers:
            started = False
            try:
                async for chunk in prov.stream(messages, profile, timeout_s=timeout_s):
                    started = True
                    yield chunk
                return
            except (ProviderError, TimeoutError, OSError) as e:
                if started:
                    log.warning("llm_stream_broken", provider=prov.name, error=str(e)[:160])
                    return
                log.info("llm_stream_failover", provider=prov.name, error=str(e)[:160])
                continue


def build_chain(settings: Any, *, transport: Any = None) -> ProviderChain:
    """Собирает цепочку из Settings (.env): LLM_CHAIN='gigachat,replay,mock'; провайдеры без ключей пропускаются."""
    from app.llm.gigachat import GigaChatProvider
    from app.llm.keys import KeyPool
    from app.llm.openai_compat import OpenAICompatProvider
    from app.replay.provider import ReplayProvider

    store = CassetteStore(settings.cassettes_dir)
    providers: list[Provider] = []
    for name in [x.strip() for x in str(settings.llm_chain).split(",") if x.strip()]:
        if name == "gigachat":
            pool = KeyPool.from_env(settings.gigachat_auth_key_1, settings.gigachat_auth_key_2)
            if len(pool) == 0:
                log.info("llm_chain_skip", provider=name, reason="нет GIGACHAT_AUTH_KEY_*")
                continue
            providers.append(
                GigaChatProvider(
                    pool,
                    oauth_url=settings.gigachat_oauth_url,
                    base_url=settings.gigachat_base_url,
                    scope=settings.gigachat_scope,
                    verify_ssl=settings.gigachat_verify_ssl,
                    transport=transport,
                )
            )
        elif name in ("openai_compat", "openai_compatible", "openrouter"):
            if not settings.openrouter_api_key and not settings.local_llm_base_url:
                log.info("llm_chain_skip", provider=name, reason="нет OPENROUTER_API_KEY / LOCAL_LLM_BASE_URL")
                continue
            providers.append(
                OpenAICompatProvider(
                    settings.openrouter_api_key,
                    settings.local_llm_base_url or settings.openrouter_base_url,
                    transport=transport,
                )
            )
        elif name == "replay":
            providers.append(ReplayProvider(store))
        elif name == "mock":
            providers.append(MockProvider())
        else:
            log.warning("llm_chain_unknown", provider=name)
    return ProviderChain(providers, record_store=store if settings.llm_record else None)


def default_profile(settings: Any) -> LLMProfile:
    if settings.llm_provider == "gigachat":
        return LLMProfile(code="gigachat_main", provider="gigachat", model=settings.gigachat_model, role="main")
    if settings.llm_provider in ("openai_compat", "openai_compatible"):
        return LLMProfile(
            code="openrouter_main",
            provider="openai_compatible",
            model="nvidia/nemotron-3-ultra-550b-a55b:free",
            base_url=settings.openrouter_base_url,
            rpm_limit=18,
            rpd_limit=1000,
        )
    return LLMProfile(code="mock", provider="mock", model="mock-rules-v1")
