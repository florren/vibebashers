"""OpenAI-совместимый провайдер через официальный openai SDK — AGENTS §6.3.

SDK retries выключены: повторы, rate limit и fallback принадлежат ProviderChain.
JSON проходит контрактную валидацию с одной корректирующей попыткой.
OpenRouter /key остаётся служебным HTTP endpoint вне Chat Completions SDK.
"""

from __future__ import annotations

import json
import math
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, cast
from urllib.parse import urlsplit

import httpx
from openai import APIConnectionError, APIError, APIStatusError, APITimeoutError, AsyncOpenAI, omit
from openai.types.chat import ChatCompletionMessageParam

from app.contracts.registry import validate_schema
from app.llm.base import LLMProfile, Message, ProviderError, Usage, extract_json
from app.llm.budget import budget_value
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


async def _empty_key() -> str:
    return ""


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
        self.api_key = api_key
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
        r = await self._client.get(f"{self.base_url}/models", headers=self._headers(self.base_url), timeout=timeout_s)
        if r.status_code >= 400:
            raise ProviderError("unavailable", f"models {r.status_code}", status=r.status_code)
        data = r.json().get("data", [])
        return [m.get("id", "") for m in data]

    async def fetch_key(self, timeout_s: float = 10.0, *, base_url: str | None = None) -> dict[str, Any]:
        """GET {base}/key. Ошибка запроса — ProviderError quota, без chat/completions."""
        base = (base_url or self.base_url).rstrip("/")
        try:
            r = await self._client.get(f"{base}/key", headers=self._headers(base), timeout=timeout_s)
        except httpx.TimeoutException as e:
            raise ProviderError("quota", f"key timeout: {e}") from e
        except httpx.HTTPError as e:
            raise ProviderError("quota", f"key: {e}") from e
        if r.status_code >= 400:
            raise ProviderError("quota", f"key {r.status_code}", status=r.status_code)
        try:
            body = r.json()
        except ValueError as exc:
            raise ProviderError("quota", "key: некорректный JSON") from exc
        if not isinstance(body, dict):
            raise ProviderError("quota", "key: не объект")
        return parse_key_payload(body)

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
        return is_openrouter(base_url) and not _skips_budget_check(profile.model)

    @staticmethod
    def _usage_known(usage: Any) -> bool:
        return all(
            isinstance(value, int) and not isinstance(value, bool) and value >= 0
            for value in (usage.prompt_tokens, usage.completion_tokens)
        )

    def _chat_client(self, base_url: str, timeout_s: float) -> AsyncOpenAI:
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
                try:
                    retry = float(exc.response.headers.get("Retry-After", "20"))
                except ValueError:
                    retry = 20.0
                return ProviderError("rate_limit", "HTTP 429", status=status, retry_after_s=retry)
            return ProviderError("unavailable", f"HTTP {status}", status=status)
        return ProviderError("bad_output", "некорректный ответ OpenAI-совместимого endpoint")

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
            try:
                try:
                    await self._before_chat(profile, base_url)
                except ProviderError as exc:
                    if usage_observed:
                        usage.cost_rub = profile.cost(usage.prompt_tokens, usage.completion_tokens)
                        exc.usage = usage
                    raise
                usage.request_count += 1
                result = await self._chat_client(base_url, timeout_s).chat.completions.create(**payload)
            except APIError as exc:
                usage_observed = False  # Ошибка upstream не подтверждает нулевой расход.
                error = self._provider_error(exc)
                if error.kind == "unavailable" and use_json_schema and error.status == 400:
                    use_json_schema = False  # Смена формата не расходует корректирующую попытку.
                    log.info("openai_compat_no_json_schema", model=profile.model)
                    continue
                raise error from exc
            if self._paid(profile, base_url) and (result.usage is None or not self._usage_known(result.usage)):
                raise ProviderError("bad_output", "расход платного ответа неизвестен: usage отсутствует")
            if result.usage is not None:
                usage_observed = self._usage_known(result.usage)
                usage.prompt_tokens += result.usage.prompt_tokens or 0
                usage.completion_tokens += result.usage.completion_tokens or 0
            raw = result.choices[0].message.content if result.choices else ""
            raw = raw or ""
            try:
                obj = extract_json(raw)
                errors = validate_schema(obj, schema)
            except ProviderError as e:
                obj, errors = {}, [e.detail]
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
        await self._before_chat(profile, base_url)
        try:
            response = await self._chat_client(base_url, timeout_s).chat.completions.create(
                model=profile.model,
                messages=cast(list[ChatCompletionMessageParam], messages),
                temperature=profile.temperature,
                stream=True,
                extra_headers={} if self._key(base_url) else {"Authorization": omit},
                stream_options={"include_usage": True} if self._paid(profile, base_url) else {},
            )
            usage_seen = False
            async with response:
                async for chunk in response:
                    usage_seen = usage_seen or (chunk.usage is not None and self._usage_known(chunk.usage))
                    if chunk.choices and chunk.choices[0].delta.content:
                        yield chunk.choices[0].delta.content
            if self._paid(profile, base_url) and not usage_seen:
                raise ProviderError("bad_output", "расход платного stream неизвестен: usage отсутствует")
        except APIError as exc:
            raise self._provider_error(exc) from exc


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
