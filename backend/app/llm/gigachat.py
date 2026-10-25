"""GigaChat через httpx (AGENTS §6.3): Authorization key → access token с автообновлением, пул ключей, structured output.

Отклонение от AGENTS (langchain-gigachat): используется прямой REST-клиент — меньше зависимостей, полный контроль таймаутов,
usage и потоковых чанков для кассет replay. API: POST {oauth_url} (Basic <auth_key>, RqUID, scope) → access_token/expires_at(ms);
POST {base_url}/chat/completions (stream SSE). Структурированный ответ: инструкция «только JSON по схеме» + разбор + повтор с ошибкой."""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.contracts.registry import validate_schema
from app.llm.base import LLMProfile, Message, ProviderError, Usage, extract_json
from app.llm.keys import ApiKey, KeyPool
from app.logging import get_logger

log = get_logger(__name__)
JSON_INSTRUCTION = (
    "Отвечай ТОЛЬКО одним JSON-объектом без пояснений и markdown, строго по JSON Schema ниже "
    "(все обязательные поля, значения enum — из списка, тексты на русском):\n{schema}"
)


class GigaChatProvider:
    name = "gigachat"

    def __init__(
        self,
        pool: KeyPool,
        *,
        oauth_url: str,
        base_url: str,
        scope: str = "GIGACHAT_API_PERS",
        verify_ssl: bool = False,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.pool = pool
        self.oauth_url = oauth_url
        self.base_url = base_url.rstrip("/")
        self.scope = scope
        self._client = httpx.AsyncClient(verify=verify_ssl, transport=transport, timeout=30.0)

    async def aclose(self) -> None:
        await self._client.aclose()

    # --- auth -------------------------------------------------------------------------------------------------------
    async def _token(self, key: ApiKey, timeout_s: float) -> str:
        if key.access_token and time.time() < key.token_expires_at - 60:
            return key.access_token
        try:
            r = await self._client.post(
                self.oauth_url,
                headers={
                    "Authorization": f"Basic {key.secret}",
                    "RqUID": str(uuid.uuid4()),
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                },
                data={"scope": self.scope},
                timeout=timeout_s,
            )
        except httpx.TimeoutException as e:
            raise ProviderError("timeout", f"oauth: {e}") from e
        except httpx.HTTPError as e:
            raise ProviderError("network", f"oauth: {e}") from e
        if r.status_code in (401, 403):
            raise ProviderError("auth", f"oauth {r.status_code}: {r.text[:200]}", status=r.status_code)
        if r.status_code == 429:
            raise ProviderError(
                "rate_limit", "oauth 429", status=429, retry_after_s=float(r.headers.get("Retry-After", 20))
            )
        if r.status_code >= 400:
            raise ProviderError("unavailable", f"oauth {r.status_code}: {r.text[:200]}", status=r.status_code)
        body = r.json()
        key.access_token = body["access_token"]
        key.token_expires_at = float(body.get("expires_at", (time.time() + 1800) * 1000)) / 1000.0
        log.info("gigachat_token", key=key.label, expires_in_s=int(key.token_expires_at - time.time()))
        return key.access_token or ""

    def _chat_base(self, profile: LLMProfile) -> str:
        return (profile.base_url or self.base_url).rstrip("/")

    def _ordered(self, messages: list[Message], extra_system: str | None = None) -> list[dict[str, str]]:
        """GigaChat принимает system только первым сообщением: склеиваем все system в одно."""
        systems = [extra_system] if extra_system else []
        rest: list[dict[str, str]] = []
        for m in messages:
            role = str(m["role"])
            content = str(m["content"])
            if role == "system":
                systems.append(content)
            else:
                rest.append({"role": role, "content": content})
        out: list[dict[str, str]] = []
        if systems:
            out.append({"role": "system", "content": "\n\n".join(systems)})
        out.extend(rest)
        return out

    # --- chat -------------------------------------------------------------------------------------------------------
    async def _chat(self, key: ApiKey, payload: dict[str, Any], profile: LLMProfile, timeout_s: float) -> httpx.Response:
        token = await self._token(key, timeout_s)
        try:
            r = await self._client.post(
                f"{self._chat_base(profile)}/chat/completions",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                json=payload,
                timeout=timeout_s,
            )
        except httpx.TimeoutException as e:
            raise ProviderError("timeout", str(e)) from e
        except httpx.HTTPError as e:
            raise ProviderError("network", str(e)) from e
        if r.status_code == 401:
            key.access_token = None  # токен протух — обновим при следующем вызове
            raise ProviderError("auth", r.text[:200], status=401)
        if r.status_code == 429:
            raise ProviderError(
                "rate_limit", r.text[:200], status=429, retry_after_s=float(r.headers.get("Retry-After", 20))
            )
        if (
            r.status_code == 402
            or (r.status_code == 403 and "quota" in r.text.lower())
            or (r.status_code == 400 and "token" in r.text.lower() and "limit" in r.text.lower())
        ):
            raise ProviderError("quota", r.text[:200], status=r.status_code)
        if r.status_code >= 400:
            raise ProviderError("unavailable", f"{r.status_code}: {r.text[:200]}", status=r.status_code)
        return r

    async def _with_keys(self, payload: dict[str, Any], profile: LLMProfile, timeout_s: float) -> tuple[httpx.Response, ApiKey]:
        tried: set[str] = set()
        last: ProviderError | None = None
        while True:
            try:
                key = self.pool.pick(exclude=tried)
            except ProviderError:
                raise last or ProviderError("quota", "нет ключей GigaChat") from None
            try:
                return await self._chat(key, payload, profile, timeout_s), key
            except ProviderError as e:
                self.pool.mark_error(key, e)
                last = e
                tried.add(key.label)
                if e.kind not in ("rate_limit", "quota", "auth"):
                    raise

    async def complete_structured(
        self, messages: list[Message], schema: dict[str, Any], profile: LLMProfile, *, timeout_s: float
    ) -> tuple[dict[str, Any], Usage, str]:
        t0 = time.perf_counter()
        sys_msg = JSON_INSTRUCTION.format(schema=json.dumps(schema, ensure_ascii=False))
        msgs = self._ordered(messages, sys_msg)
        total_usage = Usage(provider=self.name, model=profile.model)
        raw = ""
        for attempt in range(2):
            payload = {
                "model": profile.model,
                "messages": msgs,
                "temperature": profile.temperature,
                "stream": False,
                **profile.extra.get("request", {}),
            }
            r, key = await self._with_keys(payload, profile, timeout_s)
            body = r.json()
            u = body.get("usage", {})
            total_usage.prompt_tokens += int(u.get("prompt_tokens", 0))
            total_usage.completion_tokens += int(u.get("completion_tokens", 0))
            total_usage.key_label = key.label
            self.pool.add_usage(key, int(u.get("total_tokens", 0)) or total_usage.total_tokens)
            raw = body["choices"][0]["message"]["content"]
            try:
                obj = extract_json(raw)
                errors = validate_schema(obj, schema)
            except ProviderError as e:
                errors = [e.detail]
                obj = {}
            if not errors:
                total_usage.latency_ms = int((time.perf_counter() - t0) * 1000)
                total_usage.cost_rub = profile.cost(total_usage.prompt_tokens, total_usage.completion_tokens)
                return obj, total_usage, raw
            log.warning("gigachat_bad_output", attempt=attempt, errors=errors[:3])
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
        key = self.pool.pick()
        token = await self._token(key, timeout_s)
        payload = {
            "model": profile.model,
            "messages": self._ordered(messages),
            "temperature": profile.temperature,
            "stream": True,
        }
        try:
            async with self._client.stream(
                "POST",
                f"{self._chat_base(profile)}/chat/completions",
                json=payload,
                timeout=timeout_s,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "Accept": "text/event-stream",
                },
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
                    chunk = json.loads(data)
                    delta = chunk.get("choices", [{}])[0].get("delta", {}).get("content")
                    if delta:
                        yield delta
                    if chunk.get("usage"):
                        self.pool.add_usage(key, int(chunk["usage"].get("total_tokens", 0)))
        except httpx.TimeoutException as e:
            raise ProviderError("timeout", str(e)) from e
        except httpx.HTTPError as e:
            raise ProviderError("network", str(e)) from e
