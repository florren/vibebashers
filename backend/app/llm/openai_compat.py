"""OpenAI-совместимый провайдер через официальный openai SDK — AGENTS §6.3.

SDK retries выключены: повторы, rate limit и fallback принадлежат ProviderChain.
JSON проходит контрактную валидацию с одной корректирующей попыткой.
OpenRouter /key остаётся служебным HTTP endpoint вне Chat Completions SDK.
"""

from __future__ import annotations

import json
import logging
import math
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, cast
from urllib.parse import urlsplit

import httpx
from openai import APIConnectionError, APIError, APIStatusError, APITimeoutError, AsyncOpenAI, omit
from openai.types.chat import ChatCompletionMessageParam

from app.contracts.registry import validate_schema
from app.llm import accounting
from app.llm.base import LLMProfile, Message, ProviderError, Usage, extract_json
from app.llm.budget import budget_value
from app.llm.credential_boundary import (
    CredentialStreamGuard,
    observe_stream_usage,
    reject_reflection,
    response_token_counts,
    retry_after,
)
from app.llm.gigachat import JSON_INSTRUCTION, schema_for_model
from app.logging import get_logger

log = get_logger(__name__)

# Три модели сравнения (ТЗ 5.2) и запасная замена, если id исчез из GET /models.
DEFAULT_MODEL_IDS: tuple[str, ...] = (
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "openrouter/owl-alpha",
    "openai/gpt-oss-120b:free",
)
PREFERRED_REPLACEMENT = "nvidia/nemotron-3-super-120b-a12b:free"
OPENROUTER_PROFILE_MODELS: dict[str, str] = {
    "or_nemotron_ultra": DEFAULT_MODEL_IDS[0],
    "or_owl_alpha": DEFAULT_MODEL_IDS[1],
    "or_gpt_oss_120b": DEFAULT_MODEL_IDS[2],
}


def suggest_replacement(available: list[str]) -> str | None:
    """Предпочтительный id, если он в каталоге; иначе первый id с суффиксом :free."""
    if PREFERRED_REPLACEMENT in available:
        return PREFERRED_REPLACEMENT
    for model_id in available:
        if model_id.endswith(":free"):
            return model_id
    return None


def deactivation_plan(available: list[str]) -> list[dict[str, Any]]:
    """Пустой каталог не гасит профили. Иначе каждый из трёх id, которого нет, деактивируется."""
    if not available:
        return []
    present = set(available)
    suggested = suggest_replacement(available)
    return [
        {"model": model_id, "is_active": False, "suggested_model": suggested}
        for model_id in DEFAULT_MODEL_IDS
        if model_id not in present
    ]


def parse_key_payload(body: dict[str, Any]) -> dict[str, Any]:
    """Поля GET /key: balance_usd = limit_remaining; rpd 1000 на платном ярусе и 50 на free."""
    raw = body.get("data")
    data = raw if isinstance(raw, dict) else body
    is_free = bool(data.get("is_free_tier"))
    remaining = data.get("limit_remaining")
    return {
        "limit": data.get("limit"),
        "usage": data.get("usage"),
        "limit_remaining": remaining,
        "is_free_tier": data.get("is_free_tier"),
        "balance_usd": remaining,
        "rpd_limit": (
            data["free_model_daily_requests"].get("limit")
            if isinstance(data.get("free_model_daily_requests"), dict)
            else (50 if is_free else 1000)
        ),
    }


def is_openrouter(base_url: str) -> bool:
    return urlsplit(base_url).hostname == "openrouter.ai"


def _skips_budget_check(model: str) -> bool:
    """Только явный :free гарантирует, что имя модели не обходит бюджет платного API."""
    return model.endswith(":free")


def is_paid_model(profile: LLMProfile, base_url: str) -> bool:
    return is_openrouter(base_url) and not _skips_budget_check(profile.model)


def _openrouter_missing_usage_reference(result: Any, headers: httpx.Headers, secret: str | None) -> str:
    # Это metadata провайдера, а не текст модели. Конфликтующие body/header IDs
    # не дают достоверного указателя; raw upstream body/message наружу не идут.
    references = {
        value
        for value in (getattr(result, "id", None), headers.get("X-Generation-Id"))
        if isinstance(value, str)
        and 5 <= len(value) <= 128
        and value.startswith("gen-")
        and value.isascii()
        and all(char.isalnum() or char == "-" for char in value[4:])
        and (not secret or secret not in value)
    }
    details = [f"generation_id={next(iter(references))}"] if len(references) == 1 else []
    metadata = getattr(result, "model_extra", None)
    error = metadata.get("error") if isinstance(metadata, dict) else None
    code = error.get("code") if isinstance(error, dict) else None
    if type(code) is int and 100 <= code <= 599 and (not secret or secret not in str(code)):
        details.append(f"provider_error_code={code}")
    return "".join(f"; {item}" for item in details)


async def _empty_key() -> str:
    return ""


_SDK_LOGGERS = ("openai", "openai._base_client", "openai._response", "openai._legacy_response")


def _enforce_sdk_logging() -> None:
    # SDK2.54 читает OPENAI_LOG при import и DEBUG пишет body/headers/exception.
    # Наша граница владеет только этими logger: root/httpx/app logs не меняем.
    for name in _SDK_LOGGERS:
        logger = logging.getLogger(name)
        if logger.getEffectiveLevel() < logging.WARNING:
            logger.setLevel(logging.WARNING)


class OpenAICompatProvider:
    name = "openai_compatible"

    def __init__(
        self,
        api_key: str | None,
        base_url: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        app_title: str = "CX Pulse Control",
        budget_usd: float = 10.0,
        http_referer: str | None = None,
        budget_loader: Callable[[], Awaitable[float]] | None = None,
        endpoint_keys: dict[str, str | None] | None = None,
    ) -> None:
        _enforce_sdk_logging()
        self.api_key = api_key
        self.accounting = accounting.service()
        self.endpoint_keys = endpoint_keys
        self.base_url = base_url.rstrip("/")
        self.app_title = app_title
        self.budget_usd = budget_usd
        self.budget_loader = budget_loader
        self.http_referer = http_referer
        self._client = httpx.AsyncClient(transport=transport, timeout=30.0)
        self._sdk = AsyncOpenAI(
            # Явный callable не читает OPENAI_API_KEY и не отправляет фиктивный bearer
            # на keyless local endpoint. Поддерживается public API SDK 2.54.
            api_key=api_key or _empty_key,
            base_url=self.base_url,
            http_client=self._client,
            max_retries=0,
        )

    async def aclose(self) -> None:
        await self._sdk.close()

    def _key(self, base_url: str) -> str | None:
        if self.endpoint_keys is None:
            return self.api_key
        if base_url.rstrip("/") not in self.endpoint_keys:
            raise ProviderError("miss", "endpoint профиля не настроен в LLM-цепочке")
        return self.endpoint_keys[base_url.rstrip("/")]

    def _headers(self, base_url: str | None = None) -> dict[str, str]:
        h = {"Content-Type": "application/json", "X-Title": self.app_title}
        url = base_url or self.base_url
        if is_openrouter(url) and self.http_referer:
            h["HTTP-Referer"] = self.http_referer
        key = self._key(url)
        if key:
            h["Authorization"] = f"Bearer {key}"
        return h

    async def list_models(self, timeout_s: float = 10.0) -> list[str]:
        """GET /models — мастер настройки проверяет доступность моделей профиля."""
        try:
            r = await self._client.get(
                f"{self.base_url}/models", headers=self._headers(self.base_url), timeout=timeout_s
            )
        except httpx.HTTPError as exc:
            raise ProviderError("unavailable", f"models: {type(exc).__name__}") from None
        if r.status_code >= 400:
            raise ProviderError("unavailable", f"models {r.status_code}", status=r.status_code)
        try:
            body = r.json()
        except ValueError:
            raise ProviderError("unavailable", "models: некорректный JSON") from None
        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, list) or any(
            not isinstance(model, dict) or not isinstance(model.get("id"), str) or not model["id"] for model in data
        ):
            raise ProviderError("unavailable", "models: некорректный каталог")
        model_ids = [model["id"] for model in data]
        reject_reflection(model_ids, [self._key(self.base_url)])
        return model_ids

    async def fetch_key(self, timeout_s: float = 10.0, *, base_url: str | None = None) -> dict[str, Any]:
        """GET {base}/key. Ошибка запроса — ProviderError quota, без chat/completions."""
        base = (base_url or self.base_url).rstrip("/")
        try:
            r = await self._client.get(f"{base}/key", headers=self._headers(base), timeout=timeout_s)
        except httpx.TimeoutException as e:
            raise ProviderError("quota", f"key timeout: {type(e).__name__}") from None
        except httpx.HTTPError as e:
            raise ProviderError("quota", f"key: {type(e).__name__}") from None
        if r.status_code >= 400:
            raise ProviderError("quota", f"key {r.status_code}", status=r.status_code)
        try:
            body = r.json()
        except ValueError:
            raise ProviderError("quota", "key: некорректный JSON") from None
        if not isinstance(body, dict):
            raise ProviderError("quota", "key: не объект")
        public = parse_key_payload(body)
        # Только consumed projection; private unused provider labels не публикуются.
        reject_reflection(public, [self._key(base)])
        return public

    async def _before_chat(self, profile: LLMProfile, base_url: str) -> None:
        if profile.provider != "openai_compatible":
            raise ProviderError("miss", "профиль не openai_compatible")
        if not is_openrouter(base_url) or _skips_budget_check(profile.model):
            return
        budget = budget_value(await self.budget_loader() if self.budget_loader else self.budget_usd)
        if budget == 0:
            raise ProviderError("quota", "бюджет платных моделей OpenRouter исчерпан")
        info = await self.fetch_key(base_url=base_url)
        usage = info.get("usage")
        if isinstance(usage, bool) or not isinstance(usage, (int, float)) or not math.isfinite(usage) or usage < 0:
            raise ProviderError("quota", "расход OpenRouter неизвестен: платный вызов запрещён")
        remaining = info.get("limit_remaining")
        if remaining is not None:
            if (
                isinstance(remaining, bool)
                or not isinstance(remaining, (int, float))
                or not math.isfinite(remaining)
                or remaining <= 0
            ):
                raise ProviderError("quota", "остаток лимита ключа OpenRouter неизвестен или исчерпан")
        if float(usage) >= budget:
            raise ProviderError("quota", "расход OpenRouter достиг бюджета")

    @staticmethod
    def _paid(profile: LLMProfile, base_url: str) -> bool:
        return is_paid_model(profile, base_url)

    def _chat_client(self, base_url: str, timeout_s: float) -> AsyncOpenAI:
        _enforce_sdk_logging()
        headers: dict[str, Any] = self._headers(base_url)
        key = self._key(base_url)
        if not key:
            headers["Authorization"] = omit
        return self._sdk.with_options(
            base_url=base_url, timeout=timeout_s, default_headers=headers, api_key=key or _empty_key
        )

    @staticmethod
    def _provider_error(exc: APIError) -> ProviderError:
        # Ответ upstream может содержать секрет/эхо запроса: наружу идут только тип и статус.
        if isinstance(exc, APITimeoutError):
            return ProviderError("timeout", "таймаут OpenAI-совместимого endpoint")
        if isinstance(exc, APIConnectionError):
            return ProviderError("network", "OpenAI-совместимый endpoint недоступен")
        if isinstance(exc, APIStatusError):
            status = exc.status_code
            if status in (401, 403):
                return ProviderError("auth", f"HTTP {status}", status=status)
            if status == 402:
                return ProviderError("quota", "HTTP 402", status=status)
            if status == 429:
                return ProviderError(
                    "rate_limit",
                    "HTTP 429",
                    status=status,
                    retry_after_s=retry_after(exc.response.headers.get("Retry-After")),
                )
            return ProviderError("unavailable", f"HTTP {status}", status=status)
        return ProviderError("bad_output", "некорректный ответ OpenAI-совместимого endpoint")

    async def _structured_wire(
        self, payload: dict[str, Any], profile: LLMProfile, base_url: str, timeout_s: float, usage: Usage
    ) -> tuple[Any, int, int]:
        facts = accounting.KeyFacts(
            self.name, self._key(base_url), base_url, db_id=profile.api_key_id, paid=self._paid(profile, base_url)
        )
        async with self.accounting.key_scope(profile, facts, timeout_s=timeout_s) as scope:
            await self._before_chat(profile, base_url)
            async with scope.inference() as ticket:
                usage.request_count += 1
                try:
                    response = await self._chat_client(base_url, timeout_s).chat.completions.with_raw_response.create(
                        **payload
                    )
                    result = response.parse()
                except APIError as exc:
                    raise self._provider_error(exc) from None
                if result.usage is None:
                    detail = (
                        "расход платного ответа неизвестен: usage отсутствует"
                        if self._paid(profile, base_url)
                        else "расход ответа неизвестен: usage отсутствует"
                    )
                    if is_openrouter(base_url):
                        detail += _openrouter_missing_usage_reference(result, response.headers, self._key(base_url))
                    raise ProviderError("bad_output", detail)
                raw_usage = {
                    "prompt_tokens": result.usage.prompt_tokens,
                    "completion_tokens": result.usage.completion_tokens,
                }
                if getattr(result.usage, "total_tokens", None) is not None:
                    raw_usage["total_tokens"] = result.usage.total_tokens
                prompt, completion, total = response_token_counts(raw_usage, [self._key(base_url)])
                await ticket.observe(prompt, completion, total_tokens=total, final=True)
                return result, prompt, completion

    async def complete_structured(
        self, messages: list[Message], schema: dict[str, Any], profile: LLMProfile, *, timeout_s: float
    ) -> tuple[dict[str, Any], Usage, str]:
        t0 = time.perf_counter()
        base_url = (profile.base_url or self.base_url).rstrip("/")
        if profile.provider != "openai_compatible":
            raise ProviderError("miss", "профиль не openai_compatible")
        self._key(base_url)  # Не пересылаем credential другого endpoint на URL профиля.
        use_json_schema = bool(profile.extra.get("json_schema", True))
        msgs: list[dict[str, str]] = [
            {
                "role": "system",
                "content": JSON_INSTRUCTION.format(schema=json.dumps(schema_for_model(schema), ensure_ascii=False)),
            },
            *[{"role": str(m["role"]), "content": str(m["content"])} for m in messages],
        ]
        usage = Usage(provider=self.name, model=profile.model, request_count=0)
        raw = ""
        usage_observed = False
        attempt = 0
        while attempt < 2:
            payload: dict[str, Any] = {
                "model": profile.model,
                "messages": msgs,
                "temperature": profile.temperature,
                "stream": False,
                "extra_headers": {} if self._key(base_url) else {"Authorization": omit},
            }
            if "max_output_tokens" in profile.extra:
                payload["max_tokens"] = int(profile.extra["max_output_tokens"])
            if use_json_schema:
                payload["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {"name": "contract", "schema": schema, "strict": False},
                }
            else:
                payload["response_format"] = {"type": "json_object"}
            requests_before = usage.request_count
            try:
                result, prompt, completion = await self._structured_wire(payload, profile, base_url, timeout_s, usage)
            except ProviderError as error:
                if usage.request_count > requests_before:
                    usage_observed = False  # Новый wire без validated usage не равен0.
                if usage_observed:
                    usage.cost_rub = profile.cost(usage.prompt_tokens, usage.completion_tokens)
                    error.usage = usage
                if error.kind == "unavailable" and use_json_schema and error.status == 400:
                    use_json_schema = False  # Смена формата не расходует корректирующую попытку.
                    log.info("openai_compat_no_json_schema", model=profile.model)
                    continue
                raise error from None
            usage_observed = True
            usage.prompt_tokens += prompt
            usage.completion_tokens += completion
            raw = result.choices[0].message.content if result.choices else ""
            raw = raw or ""
            try:
                obj = extract_json(raw)
                errors = validate_schema(obj, schema)
            except ProviderError as e:
                obj, errors = {}, [e.detail]
            try:
                reject_reflection([raw, obj], [self._key(base_url)])
            except ProviderError as exc:
                if usage_observed:
                    usage.cost_rub = profile.cost(usage.prompt_tokens, usage.completion_tokens)
                    exc.usage = usage
                raise
            if not errors:
                usage.latency_ms = int((time.perf_counter() - t0) * 1000)
                usage.cost_rub = profile.cost(usage.prompt_tokens, usage.completion_tokens)
                return obj, usage, raw
            log.warning("openai_compat_bad_output", attempt=attempt, error_count=len(errors))
            attempt += 1
            usage.json_valid_first_try = False
            usage.structured_retries = min(attempt, 1)
            msgs += [
                {"role": "assistant", "content": raw},
                {
                    "role": "user",
                    "content": "Ответ не прошёл валидацию по схеме: "
                    + "; ".join(errors[:5])
                    + ". Верни исправленный JSON целиком.",
                },
            ]
        raise ProviderError("bad_output", "ответ не соответствует схеме после 2 попыток", usage=usage)

    async def stream(self, messages: list[Message], profile: LLMProfile, *, timeout_s: float) -> AsyncIterator[str]:
        base_url = (profile.base_url or self.base_url).rstrip("/")
        facts = accounting.KeyFacts(
            self.name, self._key(base_url), base_url, db_id=profile.api_key_id, paid=self._paid(profile, base_url)
        )
        async with self.accounting.key_scope(profile, facts, timeout_s=timeout_s, streaming=True) as scope:
            await scope.wait(self._before_chat(profile, base_url))
            async with scope.inference() as ticket:
                observed: Usage | None = None
                observed_total = 0
                try:
                    response = await scope.wait(
                        self._chat_client(base_url, timeout_s).chat.completions.create(
                            model=profile.model,
                            messages=cast(list[ChatCompletionMessageParam], messages),
                            temperature=profile.temperature,
                            stream=True,
                            extra_headers={} if self._key(base_url) else {"Authorization": omit},
                            stream_options={"include_usage": True},
                        )
                    )
                    usage_seen = False
                    guard = CredentialStreamGuard([self._key(base_url)])
                    async with response:
                        async for chunk in scope.iterate(response):
                            if chunk.usage is not None:
                                raw_usage = {
                                    "prompt_tokens": chunk.usage.prompt_tokens,
                                    "completion_tokens": chunk.usage.completion_tokens,
                                }
                                if getattr(chunk.usage, "total_tokens", None) is not None:
                                    raw_usage["total_tokens"] = chunk.usage.total_tokens
                                prompt, completion, total = response_token_counts(raw_usage, [self._key(base_url)])
                                await ticket.observe(prompt, completion, total_tokens=total)
                                observed_total = total
                                usage_seen = True
                                observed = observe_stream_usage(
                                    observed,
                                    {"prompt_tokens": prompt, "completion_tokens": completion},
                                    profile,
                                    self.name,
                                )
                            if chunk.choices and chunk.choices[0].delta.content:
                                safe = guard.feed(chunk.choices[0].delta.content)
                                if safe:
                                    yield safe
                    if not usage_seen or observed is None:
                        detail = (
                            "расход платного stream неизвестен: usage отсутствует"
                            if self._paid(profile, base_url)
                            else "расход stream неизвестен: usage отсутствует"
                        )
                        raise ProviderError("bad_output", detail)
                    await ticket.observe(
                        observed.prompt_tokens, observed.completion_tokens, total_tokens=observed_total, final=True
                    )
                    last = guard.finish()
                    if last:
                        yield last
                except ProviderError as exc:
                    if observed is not None:
                        exc.usage = observed
                    raise
                except APIError as exc:
                    error = self._provider_error(exc)
                    error.usage = observed
                    raise error from None


async def openrouter_deactivation_plan(provider: OpenAICompatProvider) -> list[dict[str, Any]]:
    """Каталог OpenRouter → план деактивации. Чужой base_url, ошибка GET и пустой список профиль не гасят."""
    if not is_openrouter(provider.base_url):
        return []
    try:
        available = await provider.list_models()
    except Exception as exc:
        log.warning("openrouter_models_unavailable", error=str(exc)[:200])
        return []
    return deactivation_plan(available)
