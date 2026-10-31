"""Цепочка провайдеров с failover (AGENTS §6.3): таймауты по контексту, любая ошибка → следующий → mock; симуляция не останавливается.

Запись кассет при LLM_RECORD=1 (успешный ответ live-провайдера → CassetteStore)."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field, replace
from typing import Any

from app.llm.base import TIMEOUTS_S, Context, LLMProfile, Message, Provider, ProviderError, Usage
from app.llm.mock import MockProvider
from app.llm.openai_compat import OPENROUTER_PROFILE_MODELS, OpenAICompatProvider
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
    model: str | None = None


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
        scenario_id: str | None = None,
        prompt_version: str | None = None,
        append_mock: bool = True,
    ) -> None:
        if append_mock and (not providers or providers[-1].name != "mock"):
            providers = [*providers, MockProvider()]  # mock всегда замыкает цепочку
        self.strict = not append_mock
        self.role_profiles: dict[str, LLMProfile] = {}
        self.providers = providers
        self.record_store = record_store
        self.limiter = rate_limiter or default_limiter
        self.timeouts = {**TIMEOUTS_S, **(timeouts or {})}
        self.scenario_id = scenario_id
        self.prompt_version = prompt_version

    def profile_for(self, role: str, default: LLMProfile) -> LLMProfile:
        return self.role_profiles.get(role, default)

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
        fallback_profile: LLMProfile | None = None,
    ) -> ChainResult:
        timeout_s = self.timeout_for(context)
        # Используем только настроенные живые профили; роль twin остаётся без изменений.
        backups: list[tuple[Provider, LLMProfile]] = []
        profiles: list[LLMProfile] = []
        if context == "normalization" and profile.provider == "gigachat" and profile.model == "GigaChat-3-Lightning":
            profiles.extend(
                p for p in self.role_profiles.values() if p.provider == "gigachat" and p.model == "GigaChat-3-Pro"
            )
        if fallback_profile is not None:
            profiles.append(fallback_profile)
        seen = {(profile.provider, profile.model, profile.base_url)}
        for reserved in profiles:
            identity = (reserved.provider, reserved.model, reserved.base_url)
            if profile.provider in ("mock", "replay") or reserved.provider in ("mock", "replay") or identity in seen:
                continue
            provider = next((p for p in self.providers if p.name == reserved.provider), None)
            if provider is not None:
                backups.append((provider, reserved))
                seen.add(identity)
        deadline = time.perf_counter() + timeout_s if backups else None
        backup_index = 0
        failed_usage = Usage(request_count=0)
        attempts: list[Attempt] = []
        last_error: ProviderError | None = None
        for prov in self.providers:
            if profile.provider in ("mock", "replay") and prov.name in ("gigachat", "openai_compatible"):
                continue
            requests = [(prov, profile)]
            for candidate, selected in requests:
                remaining = max(0.0, deadline - time.perf_counter()) if deadline else timeout_s
                if candidate.name not in ("mock", "replay") and remaining <= 0:
                    continue
                budget = remaining if candidate.name not in ("mock", "replay") else timeout_s
                if context == "normalization" and backups and candidate.name == profile.provider:
                    # Для Lightning → Pro → Ultra сохраняем 4/3/3 с; неиспользованное
                    # время получает следующая модель. Две модели сохраняют 5/5 с.
                    reserve = timeout_s * (0.3 if len(backups) > 1 else 0.5)
                    budget = max(0.0, budget - reserve * (len(backups) - backup_index))
                t0 = time.perf_counter()
                try:

                    async def invoke(
                        provider: Provider, requested: LLMProfile, limit: float
                    ) -> tuple[dict[str, Any], Usage, str]:
                        if provider.name not in ("mock", "replay"):
                            await self.limiter.acquire(requested.code, requested.rpm_limit, requested.rpd_limit)
                        return await provider.complete_structured(messages, schema, requested, timeout_s=limit)

                    obj, usage, raw = await asyncio.wait_for(invoke(candidate, selected, budget), timeout=budget)
                except TimeoutError:
                    last_error = ProviderError("timeout", "провайдер не ответил вовремя")
                    ms = int((time.perf_counter() - t0) * 1000)
                    attempts.append(
                        Attempt(candidate.name, False, ms, f"timeout {budget:.1f}s ({context})", selected.model)
                    )
                    log.warning("llm_timeout", provider=candidate.name, model=selected.model, context=context, ms=ms)
                    if (
                        context == "normalization"
                        and backup_index < len(backups)
                        and candidate.name == profile.provider
                    ):
                        requests.append(backups[backup_index])
                        backup_index += 1
                    continue
                except ProviderError as exc:
                    last_error = exc
                    ms = int((time.perf_counter() - t0) * 1000)
                    attempts.append(
                        Attempt(candidate.name, False, ms, f"{exc.kind}: {exc.detail[:160]}", selected.model)
                    )
                    if exc.usage:
                        failed_usage.prompt_tokens += exc.usage.prompt_tokens
                        failed_usage.completion_tokens += exc.usage.completion_tokens
                        failed_usage.cost_rub += exc.usage.cost_rub
                        failed_usage.request_count += exc.usage.request_count
                        failed_usage.structured_retries += exc.usage.structured_retries
                    (log.info if exc.kind == "miss" else log.warning)(
                        "llm_provider_error", provider=candidate.name, model=selected.model, kind=exc.kind, ms=ms
                    )
                    # Ошибка формата/доступности быстрой модели не должна сразу вести к mock.
                    # При auth/quota/429 сохраняем штатный failover без дополнительных попыток другими моделями.
                    if (
                        backup_index < len(backups)
                        and candidate.name == profile.provider
                        and (
                            exc.kind in ("bad_output", "unavailable")
                            or (context == "normalization" and exc.kind == "timeout")
                        )
                    ):
                        requests.append(backups[backup_index])
                        backup_index += 1
                    continue
                except Exception as exc:  # любая иная ошибка — тоже failover, с полным логом
                    last_error = ProviderError("unavailable", type(exc).__name__)
                    ms = int((time.perf_counter() - t0) * 1000)
                    attempts.append(
                        Attempt(candidate.name, False, ms, f"{type(exc).__name__}: {str(exc)[:160]}", selected.model)
                    )
                    log.exception("llm_provider_crash", provider=candidate.name)
                    continue
                ms = int((time.perf_counter() - t0) * 1000)
                attempts.append(Attempt(candidate.name, True, ms, model=usage.model or selected.model))
                if self.record_store is not None and usage.source == "live":
                    self.record_store.record(
                        candidate.name,
                        selected.model,
                        messages,
                        schema,
                        response=obj,
                        usage=usage.as_dict(),
                        scenario_id=self.scenario_id,
                        prompt_version=self.prompt_version,
                    )
                if any(not a.ok for a in attempts):
                    log.info(
                        "llm_failover",
                        used=candidate.name,
                        model=selected.model,
                        failed=[a.provider for a in attempts if not a.ok],
                    )
                usage = replace(
                    usage,
                    prompt_tokens=usage.prompt_tokens + failed_usage.prompt_tokens,
                    completion_tokens=usage.completion_tokens + failed_usage.completion_tokens,
                    cost_rub=usage.cost_rub + failed_usage.cost_rub,
                    request_count=usage.request_count + failed_usage.request_count,
                    structured_retries=usage.structured_retries + failed_usage.structured_retries,
                    json_valid_first_try=usage.json_valid_first_try and not any(not a.ok for a in attempts),
                    latency_ms=sum(a.ms for a in attempts),
                )
                return ChainResult(obj, usage, raw, candidate.name, attempts)
        if self.strict and last_error is not None:
            raise last_error
        raise ProviderError(
            "unavailable", "; ".join(a.error or a.provider for a in attempts) or "нет доступного провайдера"
        )

    async def stream(
        self, messages: list[Message], profile: LLMProfile, *, context: Context | str = "default"
    ) -> AsyncIterator[str]:
        """Поток токенов: первый провайдер, отдавший хотя бы один чанк, становится источником; ошибка до первого чанка → следующий."""
        timeout_s = self.timeout_for(context)
        for prov in self.providers:
            if profile.provider in ("mock", "replay") and prov.name in ("gigachat", "openai_compatible"):
                continue
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
    """Собирает цепочку из Settings (.env): LLM_CHAIN='gigachat,openai_compat,replay,mock'; провайдеры без ключей пропускаются."""
    from app.llm.gigachat import GigaChatProvider
    from app.llm.keys import KeyPool
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
                    ca_bundle_file=getattr(settings, "gigachat_ca_bundle_file", None),
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
                    budget_usd=float(settings.openrouter_budget_usd),
                    http_referer=f"http://localhost:{settings.app_port}",
                )
            )
        elif name == "replay":
            providers.append(ReplayProvider(store))
        elif name == "mock":
            providers.append(MockProvider())
        else:
            log.warning("llm_chain_unknown", provider=name)
    return ProviderChain(providers, record_store=store if settings.llm_record else None)


def live_recording_possible(settings: Any) -> bool:
    """True, если build_chain не пропустит ни GigaChat, ни OpenAI-совместимый live-провайдер."""
    from app.llm.keys import KeyPool

    for name in [x.strip() for x in str(settings.llm_chain).split(",") if x.strip()]:
        if name == "gigachat":
            if len(KeyPool.from_env(settings.gigachat_auth_key_1, settings.gigachat_auth_key_2)) > 0:
                return True
        elif name in ("openai_compat", "openai_compatible", "openrouter"):
            if settings.openrouter_api_key or settings.local_llm_base_url:
                return True
    return False


def default_profile(settings: Any) -> LLMProfile:
    if settings.llm_provider == "gigachat":
        return LLMProfile(
            code="gigachat_main",
            provider="gigachat",
            model=settings.gigachat_model,
            role="main",
            base_url=settings.gigachat_base_url,
        )
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


def profile_by_code(settings: Any, code: str) -> LLMProfile:
    """Три кода OpenRouter из yaml и local_openai: base_url из LOCAL_LLM_BASE_URL, ключ не обязателен."""
    if code == "local_openai":
        return LLMProfile(
            code="local_openai",
            provider="openai_compatible",
            model="local",
            role="bench_only",
            base_url=settings.local_llm_base_url or None,
            extra={"local": True},
        )
    model = OPENROUTER_PROFILE_MODELS.get(code)
    if model is None:
        raise ProviderError("miss", f"неизвестный профиль {code}")
    return LLMProfile(
        code=code,
        provider="openai_compatible",
        model=model,
        role="bench_only",
        base_url=settings.openrouter_base_url,
        rpm_limit=18,
        rpd_limit=1000,
    )
