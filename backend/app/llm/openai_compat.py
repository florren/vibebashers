"""OpenAI-совместимый провайдер (OpenRouter, локальная модель) через httpx — AGENTS §6.3.

Structured output: response_format json_schema (если модель поддерживает), иначе json_object + инструкция; ответ валидируется
по схеме, одна повторная попытка с текстом ошибок. Отклонение: вместо openai SDK — httpx (единый транспорт с GigaChat и replay).
Для openrouter.ai к X-Title добавляется HTTP-Referer. Платная модель сверяет расход с бюджетом через GET /key до chat/completions."""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.contracts.registry import validate_schema
from app.llm.base import LLMProfile, Message, ProviderError, Usage, extract_json
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
        "rpd_limit": 50 if is_free else 1000,
    }


def _is_openrouter(base_url: str) -> bool:
    return "openrouter.ai" in base_url


def _skips_budget_check(model: str) -> bool:
    """Три id по умолчанию и любой :free не ходят в GET /key перед chat/completions."""
    return model in DEFAULT_MODEL_IDS or model.endswith(":free")


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
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.app_title = app_title
        self.budget_usd = budget_usd
        self.http_referer = http_referer
        self._client = httpx.AsyncClient(transport=transport, timeout=30.0)

    async def aclose(self) -> None:
        await self._client.aclose()

    def _headers(self, base_url: str | None = None) -> dict[str, str]:
        h = {"Content-Type": "application/json", "X-Title": self.app_title}
        url = base_url or self.base_url
        if _is_openrouter(url) and self.http_referer:
            h["HTTP-Referer"] = self.http_referer
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
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
        body = r.json()
        if not isinstance(body, dict):
            raise ProviderError("quota", "key: не объект")
        return parse_key_payload(body)

    async def _before_chat(self, profile: LLMProfile, base_url: str) -> None:
        if profile.provider != "openai_compatible":
            raise ProviderError("miss", "профиль не openai_compatible")
        if not _is_openrouter(base_url) or _skips_budget_check(profile.model):
            return
        info = await self.fetch_key(base_url=base_url)
        usage = info.get("usage")
        if isinstance(usage, (int, float)) and not isinstance(usage, bool) and float(usage) >= float(self.budget_usd):
            raise ProviderError("quota", "расход OpenRouter достиг бюджета")

    async def _post(self, url: str, payload: dict[str, Any], timeout_s: float, *, base_url: str) -> httpx.Response:
        try:
            r = await self._client.post(url, headers=self._headers(base_url), json=payload, timeout=timeout_s)
        except httpx.TimeoutException as e:
            raise ProviderError("timeout", str(e)) from e
        except httpx.HTTPError as e:
            raise ProviderError("network", str(e)) from e
        if r.status_code in (401, 403):
            raise ProviderError("auth", r.text[:200], status=r.status_code)
        if r.status_code == 429:
            raise ProviderError(
                "rate_limit", r.text[:200], status=429, retry_after_s=float(r.headers.get("Retry-After", 20))
            )
        if r.status_code == 402:
            raise ProviderError("quota", r.text[:200], status=402)
        if r.status_code >= 400:
            raise ProviderError("unavailable", f"{r.status_code}: {r.text[:200]}", status=r.status_code)
        return r

    async def complete_structured(
        self, messages: list[Message], schema: dict[str, Any], profile: LLMProfile, *, timeout_s: float
    ) -> tuple[dict[str, Any], Usage, str]:
        t0 = time.perf_counter()
        base_url = (profile.base_url or self.base_url).rstrip("/")
        await self._before_chat(profile, base_url)
        use_json_schema = bool(profile.extra.get("json_schema", True))
        msgs: list[dict[str, str]] = [
            {
                "role": "system",
                "content": JSON_INSTRUCTION.format(schema=json.dumps(schema_for_model(schema), ensure_ascii=False)),
            },
            *[{"role": str(m["role"]), "content": str(m["content"])} for m in messages],
        ]
        usage = Usage(provider=self.name, model=profile.model)
        raw = ""
        for attempt in range(2):
            payload: dict[str, Any] = {
                "model": profile.model,
                "messages": msgs,
                "temperature": profile.temperature,
                "stream": False,
            }
            if use_json_schema:
                payload["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {"name": "contract", "schema": schema, "strict": False},
                }
            else:
                payload["response_format"] = {"type": "json_object"}
            try:
                r = await self._post(f"{base_url}/chat/completions", payload, timeout_s, base_url=base_url)
            except ProviderError as e:
                if e.kind == "unavailable" and use_json_schema and e.status == 400:
                    use_json_schema = False  # модель не умеет json_schema — повторяем с json_object
                    log.info("openai_compat_no_json_schema", model=profile.model)
                    continue
                raise
            body = r.json()
            u = body.get("usage", {})
            usage.prompt_tokens += int(u.get("prompt_tokens", 0))
            usage.completion_tokens += int(u.get("completion_tokens", 0))
            raw = body["choices"][0]["message"]["content"] or ""
            try:
                obj = extract_json(raw)
                errors = validate_schema(obj, schema)
            except ProviderError as e:
                obj, errors = {}, [e.detail]
            if not errors:
                usage.latency_ms = int((time.perf_counter() - t0) * 1000)
                usage.cost_rub = profile.cost(usage.prompt_tokens, usage.completion_tokens)
                return obj, usage, raw
            log.warning("openai_compat_bad_output", attempt=attempt, errors=errors[:3])
            msgs += [
                {"role": "assistant", "content": raw},
                {
                    "role": "user",
                    "content": "Ответ не прошёл валидацию по схеме: "
                    + "; ".join(errors[:5])
                    + ". Верни исправленный JSON целиком.",
                },
            ]
        raise ProviderError("bad_output", f"ответ не соответствует схеме после 2 попыток: {raw[:200]!r}")

    async def stream(self, messages: list[Message], profile: LLMProfile, *, timeout_s: float) -> AsyncIterator[str]:
        base_url = (profile.base_url or self.base_url).rstrip("/")
        await self._before_chat(profile, base_url)
        payload = {
            "model": profile.model,
            "messages": [{"role": str(m["role"]), "content": str(m["content"])} for m in messages],
            "temperature": profile.temperature,
            "stream": True,
        }
        try:
            async with self._client.stream(
                "POST",
                f"{base_url}/chat/completions",
                headers=self._headers(base_url),
                json=payload,
                timeout=timeout_s,
            ) as r:
                if r.status_code >= 400:
                    body = await r.aread()
                    raise ProviderError(
                        "rate_limit" if r.status_code == 429 else "unavailable",
                        body[:200].decode(errors="ignore"),
                        status=r.status_code,
                    )
                async for line in r.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    delta = json.loads(data).get("choices", [{}])[0].get("delta", {}).get("content")
                    if delta:
                        yield delta
        except httpx.TimeoutException as e:
            raise ProviderError("timeout", str(e)) from e
        except httpx.HTTPError as e:
            raise ProviderError("network", str(e)) from e


async def openrouter_deactivation_plan(provider: OpenAICompatProvider) -> list[dict[str, Any]]:
    """Каталог OpenRouter → план деактивации. Чужой base_url, ошибка GET и пустой список профиль не гасят."""
    if not _is_openrouter(provider.base_url):
        return []
    try:
        available = await provider.list_models()
    except Exception as exc:
        log.warning("openrouter_models_unavailable", error=str(exc)[:200])
        return []
    return deactivation_plan(available)
