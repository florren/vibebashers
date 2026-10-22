"""OpenAI-совместимый провайдер (OpenRouter, локальная модель) через httpx — AGENTS §6.3.

Structured output: response_format json_schema (если модель поддерживает), иначе json_object + инструкция; ответ валидируется
по схеме, одна повторная попытка с текстом ошибок. Отклонение: вместо openai SDK — httpx (единый транспорт с GigaChat и replay)."""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.contracts.registry import validate_schema
from app.llm.base import LLMProfile, Message, ProviderError, Usage, extract_json
from app.llm.gigachat import JSON_INSTRUCTION
from app.logging import get_logger

log = get_logger(__name__)


class OpenAICompatProvider:
    name = "openai_compatible"

    def __init__(
        self,
        api_key: str | None,
        base_url: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        app_title: str = "CX Pulse Control",
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.app_title = app_title
        self._client = httpx.AsyncClient(transport=transport, timeout=30.0)

    async def aclose(self) -> None:
        await self._client.aclose()

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json", "X-Title": self.app_title}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    async def list_models(self, timeout_s: float = 10.0) -> list[str]:
        """GET /models — мастер настройки проверяет доступность моделей профиля."""
        r = await self._client.get(f"{self.base_url}/models", headers=self._headers(), timeout=timeout_s)
        if r.status_code >= 400:
            raise ProviderError("unavailable", f"models {r.status_code}", status=r.status_code)
        data = r.json().get("data", [])
        return [m.get("id", "") for m in data]

    async def _post(self, url: str, payload: dict[str, Any], timeout_s: float) -> httpx.Response:
        try:
            r = await self._client.post(url, headers=self._headers(), json=payload, timeout=timeout_s)
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
        use_json_schema = bool(profile.extra.get("json_schema", True))
        msgs: list[dict[str, str]] = [
            {"role": "system", "content": JSON_INSTRUCTION.format(schema=json.dumps(schema, ensure_ascii=False))},
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
                r = await self._post(f"{base_url}/chat/completions", payload, timeout_s)
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
        payload = {
            "model": profile.model,
            "messages": [{"role": str(m["role"]), "content": str(m["content"])} for m in messages],
            "temperature": profile.temperature,
            "stream": True,
        }
        try:
            async with self._client.stream(
                "POST", f"{base_url}/chat/completions", headers=self._headers(), json=payload, timeout=timeout_s
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
