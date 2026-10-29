"""GigaChat через httpx (AGENTS §6.3): Authorization key → access token с автообновлением, пул ключей, structured output.

Отклонение от AGENTS (langchain-gigachat): используется прямой REST-клиент — меньше зависимостей, полный контроль таймаутов,
usage и потоковых чанков для кассет replay. API: POST {oauth_url} (Basic <auth_key>, RqUID, scope) → access_token/expires_at(ms);
POST {base_url}/chat/completions (stream SSE). Структурированный ответ: инструкция «только JSON по схеме» + разбор + повтор с ошибкой."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from weakref import WeakKeyDictionary

import httpx

from app.contracts.registry import validate_schema
from app.llm.base import LLMProfile, Message, ProviderError, Usage, extract_json
from app.llm.keys import ApiKey, KeyPool
from app.logging import get_logger

log = get_logger(__name__)
_PERS_LOCKS: WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock] = WeakKeyDictionary()


@asynccontextmanager
async def generation_slot(scope: str) -> AsyncIterator[None]:
    """Freemium/PERS: один поток на процесс, включая разные профили и ключи."""
    if scope == "GIGACHAT_API_PERS":
        lock = _PERS_LOCKS.setdefault(asyncio.get_running_loop(), asyncio.Lock())
        async with lock:
            yield
    else:
        yield


def _bad_authorization(status: int, text: str) -> bool:
    """400 из-за нечитаемого Authorization — ключ непригоден, это не квота и не «нет модели»."""
    if status != 400:
        return False
    low = text.lower()
    if "token" in low and "limit" in low:
        return False
    return "authorization" in low or "decode" in low


JSON_INSTRUCTION = (
    "Отвечай ТОЛЬКО одним JSON-объектом без пояснений и markdown, строго по JSON Schema ниже "
    "(все обязательные поля, значения enum — из списка, тексты на русском). "
    "Не копируй служебные поля схемы (title, $id, examples) — их нет в ответе:\n{schema}"
)

LIGHTNING_JSON_INSTRUCTION = (
    "Верни РЕЗУЛЬТАТ выполнения задачи: один JSON-объект с конкретными значениями полей, без пояснений и markdown. "
    "Ниже дана JSON Schema — это описание формата результата, а НЕ шаблон ответа. "
    "Не возвращай саму схему: type, properties, required, enum, anyOf, $defs и $ref — служебные ключи схемы. "
    "В ответе должны быть поля из properties, все обязательные поля из required; значения enum выбирай из списка. "
    "Для nullable-поля используй конкретное значение либо null, а не описание anyOf. Тексты пиши на русском. "
    "JSON Schema формата результата:\n{schema}"
)

_SCHEMA_META = frozenset({"$schema", "$id", "title", "description", "examples"})


def schema_for_model(schema: dict[str, Any]) -> dict[str, Any]:
    """Схема для промпта: без title/$id/examples, чтобы модель не возвращала заголовок схемы как ответ."""
    return {k: v for k, v in schema.items() if k not in _SCHEMA_META}


class GigaChatProvider:
    name = "gigachat"

    def __init__(
        self,
        pool: KeyPool,
        *,
        oauth_url: str,
        base_url: str,
        scope: str = "GIGACHAT_API_PERS",
        verify_ssl: bool = True,
        ca_bundle_file: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.pool = pool
        self.oauth_url = oauth_url
        self.base_url = base_url.rstrip("/")
        self.scope = scope
        from app.llm.tls import context

        if not verify_ssl:
            raise ValueError("GigaChat требует проверку TLS; настройте GIGACHAT_CA_BUNDLE_FILE")
        self._client = httpx.AsyncClient(verify=context(ca_bundle_file), transport=transport, timeout=30.0)

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
        if r.status_code in (401, 403) or _bad_authorization(r.status_code, r.text):
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
    async def _chat(
        self, key: ApiKey, payload: dict[str, Any], profile: LLMProfile, timeout_s: float
    ) -> httpx.Response:
        token = await self._token(key, timeout_s)
        try:
            async with generation_slot(self.scope):
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
        if r.status_code in (401, 403) or _bad_authorization(r.status_code, r.text):
            key.access_token = None
            if r.status_code == 403 and "quota" in r.text.lower():
                raise ProviderError("quota", r.text[:200], status=403)
            raise ProviderError("auth", r.text[:200], status=r.status_code)
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

    async def _with_keys(
        self, payload: dict[str, Any], profile: LLMProfile, timeout_s: float, usage: Usage | None = None
    ) -> tuple[httpx.Response, ApiKey]:
        tried: set[str] = set()
        last: ProviderError | None = None
        while True:
            try:
                key = self.pool.pick(exclude=tried)
            except ProviderError:
                raise last or ProviderError("quota", "нет ключей GigaChat") from None
            try:
                if usage is not None:
                    usage.request_count += 1
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
        if profile.provider == "openai_compatible":
            raise ProviderError("miss", "профиль openai_compatible")
        t0 = time.perf_counter()
        # Уточнение нужно Lightning; общая замена ухудшила product accuracy Pro в live lite_v1.
        instruction = (
            LIGHTNING_JSON_INSTRUCTION if profile.model.split(":")[0] == "GigaChat-3-Lightning" else JSON_INSTRUCTION
        )
        sys_msg = instruction.format(schema=json.dumps(schema_for_model(schema), ensure_ascii=False))
        msgs = self._ordered(messages, sys_msg)
        total_usage = Usage(provider=self.name, model=profile.model, request_count=0)
        raw = ""
        for attempt in range(max(1, min(2, int(profile.extra.get("structured_attempts", 2))))):
            payload = {
                **profile.extra.get("request", {}),
                "model": profile.model,
                "messages": msgs,
                "temperature": profile.temperature,
                "stream": False,
            }
            try:
                r, key = await self._with_keys(payload, profile, timeout_s, total_usage)
            except ProviderError as exc:
                exc.usage = total_usage
                raise
            body = r.json()
            total_usage.model = str(body.get("model") or profile.model)
            u = body.get("usage", {})
            total_usage.prompt_tokens += int(u.get("prompt_tokens", 0))
            total_usage.completion_tokens += int(u.get("completion_tokens", 0))
            total_usage.key_label = key.label
            self.pool.add_usage(
                key,
                int(u.get("total_tokens", 0)) or int(u.get("prompt_tokens", 0)) + int(u.get("completion_tokens", 0)),
            )
            raw = body["choices"][0]["message"]["content"]
            try:
                obj = extract_json(raw)
                errors = validate_schema(obj, schema)
            except ProviderError as e:
                errors = [e.detail]
                obj = {}
            if not errors:
                total_usage.json_valid_first_try = total_usage.request_count == 1
                total_usage.latency_ms = int((time.perf_counter() - t0) * 1000)
                total_usage.cost_rub = profile.cost(total_usage.prompt_tokens, total_usage.completion_tokens)
                return obj, total_usage, raw
            total_usage.json_valid_first_try = False
            total_usage.structured_retries = attempt + 1
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
        total_usage.latency_ms = int((time.perf_counter() - t0) * 1000)
        total_usage.structured_retries = max(0, total_usage.request_count - 1)
        raise ProviderError("bad_output", "ответ не соответствует схеме после попыток исправления", usage=total_usage)

    async def stream(self, messages: list[Message], profile: LLMProfile, *, timeout_s: float) -> AsyncIterator[str]:
        if profile.provider == "openai_compatible":
            raise ProviderError("miss", "профиль openai_compatible")
        key = self.pool.pick()
        token = await self._token(key, timeout_s)
        payload = {
            **profile.extra.get("request", {}),
            "model": profile.model,
            "messages": self._ordered(messages),
            "temperature": profile.temperature,
            "stream": True,
        }
        try:
            async with (
                generation_slot(self.scope),
                self._client.stream(
                    "POST",
                    f"{self._chat_base(profile)}/chat/completions",
                    json=payload,
                    timeout=timeout_s,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                        "Accept": "text/event-stream",
                    },
                ) as r,
            ):
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
