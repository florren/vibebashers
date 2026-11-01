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
from contextlib import asynccontextmanager, suppress
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


CONNECT_TIMEOUT_S = 2.0


def request_timeout(budget: float) -> httpx.Timeout:
    """Не расходуем бюджет генерации на зависший TCP/TLS; пул попробует другой ключ."""
    return httpx.Timeout(budget, connect=min(CONNECT_TIMEOUT_S, budget))


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
        self._token_locks: dict[str, asyncio.Lock] = {}
        self._auth_task: asyncio.Task[None] | None = None
        from app.llm.tls import context

        if not verify_ssl:
            raise ValueError("GigaChat требует проверку TLS; настройте GIGACHAT_CA_BUNDLE_FILE")
        self._client = httpx.AsyncClient(
            verify=context(ca_bundle_file),
            transport=transport,
            timeout=30.0,
            limits=httpx.Limits(keepalive_expiry=60.0),
        )

    async def stop_auth_refresh(self) -> None:
        """Смена цепочки останавливает фон, сохраняя HTTP-клиент для уже выполняющихся запросов."""
        if self._auth_task is not None:
            self._auth_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._auth_task
            self._auth_task = None

    async def aclose(self) -> None:
        await self.stop_auth_refresh()
        await self._client.aclose()

    async def _request(
        self, method: str, key: ApiKey, url: str, *, penalize_cancellation: bool = True, **kwargs: Any
    ) -> httpx.Response:
        try:
            return await self._client.request(method, url, **kwargs)
        except asyncio.CancelledError:
            # Только отмена активного I/O, а не ожидания общего generation_slot.
            # Резервная модель не должна повторно использовать зависший ключ.
            if penalize_cancellation:
                self.pool.mark_error(key, ProviderError("timeout", "HTTP-запрос отменён"))
            raise

    async def prepare(self, profiles: list[LLMProfile], *, timeout_s: float = 12.0) -> bool:
        """Холодные OAuth/TLS до готовности сервиса; GET /models не генерирует токены."""
        bases = {self._chat_base(p) for p in profiles if p.provider == self.name}
        if not bases:
            return True
        t0 = time.perf_counter()
        deadline = t0 + timeout_s
        ready: set[str] = set()
        keys = [k for k in self.pool.keys if k.available()]
        # Второй проход нужен при неудаче первой попытки подготовки.
        # Ключи с 429 отсекаются _token, auth — is_active; общий дедлайн прежний.
        for _ in range(2):
            for index, key in enumerate(keys):
                if not key.is_active or time.perf_counter() >= deadline:
                    continue
                budget = max(0.0, (deadline - time.perf_counter()) / (len(keys) - index))
                try:
                    async with asyncio.timeout(budget):
                        token = await self._token(key, budget, proactive=True)
                        for base in sorted(bases - ready):
                            response = await self._request(
                                "GET",
                                key,
                                f"{base}/models",
                                headers={"Authorization": f"Bearer {token}"},
                                timeout=httpx.Timeout(budget),
                            )
                            if response.status_code == 429:
                                raise ProviderError(
                                    "rate_limit",
                                    "models 429",
                                    retry_after_s=float(response.headers.get("Retry-After", 20)),
                                )
                            if response.status_code >= 400:
                                raise ProviderError("unavailable", f"models {response.status_code}")
                            ready.add(base)
                except (TimeoutError, httpx.HTTPError, ProviderError) as exc:
                    error = (
                        exc
                        if isinstance(exc, ProviderError)
                        else ProviderError(
                            "timeout" if isinstance(exc, (TimeoutError, httpx.TimeoutException)) else "network",
                            f"подготовка: {type(exc).__name__}",
                        )
                    )
                    self.pool.mark_error(key, error)
            if ready == bases:
                break
        ok = ready == bases
        log.info("gigachat_prepared", ok=ok, ms=int((time.perf_counter() - t0) * 1000))
        if self._auth_task is None or self._auth_task.done():
            self._auth_task = asyncio.create_task(self._auth_loop(), name="gigachat-auth-refresh")
        return ok

    async def refresh_auth(self, *, timeout_s: float = 12.0) -> None:
        """Обновление за три минуты до истечения не расходует бюджет генерации."""
        for key in self.pool.keys:
            if not key.available() or (key.access_token and time.time() < key.token_expires_at - 180):
                continue
            try:
                async with asyncio.timeout(timeout_s):
                    async with self._token_locks.setdefault(key.label, asyncio.Lock()):
                        if not key.available():
                            continue
                        await self._refresh_token(key, timeout_s, proactive=True)
            except (TimeoutError, httpx.HTTPError, ProviderError, ValueError, KeyError) as exc:
                # Сетевая ошибка подготовки не отменяет ещё рабочий токен. 429/auth обязательны.
                if isinstance(exc, ProviderError) and exc.kind in ("auth", "rate_limit", "quota"):
                    self.pool.mark_error(key, exc)
                log.warning("gigachat_auth_refresh_failed", key=key.label, error_type=type(exc).__name__)

    async def _auth_loop(self) -> None:
        while True:
            await asyncio.sleep(30)
            try:
                await self.refresh_auth()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # Защита фонового worker; следующий цикл повторяет подготовку.
                log.exception("gigachat_auth_refresh_failed", error_type=type(exc).__name__)

    # --- auth -------------------------------------------------------------------------------------------------------
    async def _token(self, key: ApiKey, timeout_s: float, *, proactive: bool = False) -> str:
        # Пока фон обновляет токен заранее, генерация использует ещё действующий кэш.
        wait = key.cooldown_until - time.monotonic()
        if wait > 0 and (key.last_error or "").startswith("rate_limit:"):
            raise ProviderError("rate_limit", "ключ временно на паузе после 429", retry_after_s=wait)
        if key.is_active and key.access_token and time.time() < key.token_expires_at - (180 if proactive else 60):
            return key.access_token
        # Одновременные узлы/профили используют один кэш ключа без всплеска OAuth-запросов.
        async with self._token_locks.setdefault(key.label, asyncio.Lock()):
            wait = key.cooldown_until - time.monotonic()
            if wait > 0 and not (key.last_error or "").startswith(("timeout:", "network:")):
                raise ProviderError("rate_limit", "ключ временно на паузе после 429", retry_after_s=wait)
            return await self._refresh_token(key, timeout_s, proactive=proactive)

    async def _refresh_token(self, key: ApiKey, timeout_s: float, *, proactive: bool = False) -> str:
        if key.access_token and time.time() < key.token_expires_at - (180 if proactive else 60):
            return key.access_token
        try:
            r = await self._request(
                "POST",
                key,
                self.oauth_url,
                headers={
                    "Authorization": f"Basic {key.secret}",
                    "RqUID": str(uuid.uuid4()),
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                },
                data={"scope": self.scope},
                # Холодный OAuth/TLS фона может занять больше двух секунд; генерация не ждёт его.
                timeout=httpx.Timeout(timeout_s) if proactive else request_timeout(timeout_s),
                penalize_cancellation=not proactive,
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
                r = await self._request(
                    "POST",
                    key,
                    f"{self._chat_base(profile)}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                    json=payload,
                    timeout=request_timeout(timeout_s),
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
        deadline = time.perf_counter() + timeout_s
        last: ProviderError | None = None
        while True:
            try:
                key = self.pool.pick(exclude=tried)
            except ProviderError as exc:
                raise last or exc from None
            try:
                if usage is not None:
                    usage.request_count += 1
                remaining = max(0.0, deadline - time.perf_counter())
                async with asyncio.timeout(remaining):
                    return await self._chat(key, payload, profile, remaining), key
            except TimeoutError as exc:
                raise ProviderError("timeout", "бюджет запроса исчерпан") from exc
            except ProviderError as e:
                self.pool.mark_error(key, e)
                last = e
                tried.add(key.label)
                if e.kind not in ("rate_limit", "quota", "auth", "timeout", "network"):
                    raise
                if time.perf_counter() >= deadline:
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
                remaining = max(0.0, timeout_s - (time.perf_counter() - t0))
                r, key = await self._with_keys(payload, profile, remaining, total_usage)
            except ProviderError as exc:
                total_usage.cost_rub = profile.cost(total_usage.prompt_tokens, total_usage.completion_tokens)
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
        total_usage.cost_rub = profile.cost(total_usage.prompt_tokens, total_usage.completion_tokens)
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
