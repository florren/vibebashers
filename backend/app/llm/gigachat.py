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
from contextlib import AsyncExitStack, asynccontextmanager, suppress
from contextvars import ContextVar
from typing import Any
from weakref import WeakKeyDictionary

import httpx

from app.contracts.registry import validate_schema
from app.llm import accounting
from app.llm.base import LLMProfile, Message, ProviderError, Usage, extract_json
from app.llm.credential_boundary import (
    CredentialStreamGuard,
    observe_stream_usage,
    reject_reflection,
    response_token_counts,
    retry_after,
)
from app.llm.gigachat_balance import parse_balance, require_balance
from app.llm.keys import ApiKey, KeyPool
from app.llm.scheduling import GenerationQueue
from app.logging import get_logger

log = get_logger(__name__)
_PERS_LOCKS: WeakKeyDictionary[asyncio.AbstractEventLoop, GenerationQueue] = WeakKeyDictionary()
_PERS_SLOT_HELD: ContextVar[bool] = ContextVar("gigachat_pers_slot_held", default=False)


class _InferenceStarted(ProviderError):
    """Marks an origin-backed wire attempt whose unknown usage must remain audited."""


@asynccontextmanager
async def generation_slot(scope: str) -> AsyncIterator[None]:
    """Freemium/PERS: один поток на процесс, включая разные профили и ключи."""
    if scope == "GIGACHAT_API_PERS" and not _PERS_SLOT_HELD.get():
        queue = _PERS_LOCKS.setdefault(asyncio.get_running_loop(), GenerationQueue())
        async with queue.slot():
            yield
    else:
        yield


@asynccontextmanager
async def generation_context(scope: str) -> AsyncIterator[None]:
    """Только цепочка передаёт уже занятый слот вложенному SDK-вызову."""
    async with generation_slot(scope):
        token = _PERS_SLOT_HELD.set(scope == "GIGACHAT_API_PERS")
        try:
            yield
        finally:
            _PERS_SLOT_HELD.reset(token)


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

    def generation_context(self) -> Any:
        """Цепочка ждёт PERS-слот до запуска deadline; вложенный SDK использует тот же слот."""
        return generation_context(self.scope)

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
        self.accounting = accounting.service()
        for key in pool.keys:
            key.durable_accounting = self.accounting.durable
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
                                    retry_after_s=retry_after(response.headers.get("Retry-After")),
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
            raise ProviderError("timeout", f"oauth: {type(e).__name__}") from None
        except httpx.HTTPError as e:
            raise ProviderError("network", f"oauth: {type(e).__name__}") from None
        if r.status_code in (401, 403) or _bad_authorization(r.status_code, r.text):
            raise ProviderError("auth", f"oauth HTTP {r.status_code}", status=r.status_code)
        if r.status_code == 429:
            raise ProviderError(
                "rate_limit", "oauth 429", status=429, retry_after_s=retry_after(r.headers.get("Retry-After"))
            )
        if r.status_code >= 400:
            raise ProviderError("unavailable", f"oauth HTTP {r.status_code}", status=r.status_code)
        try:
            body = r.json()
        except ValueError:
            raise ProviderError("bad_output", "oauth: некорректный JSON") from None
        if not isinstance(body, dict):
            raise ProviderError("bad_output", "oauth: ожидается JSON object")
        # access_token — ожидаемое private поле OAuth, оно не возвращается в API/trace.
        reject_reflection({name: value for name, value in body.items() if name != "access_token"}, [key.secret])
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
    async def fetch_balance(self, key: ApiKey, profile: LLMProfile, *, timeout_s: float) -> dict[str, int]:
        """Read provider package availability; never infer historic consumption."""
        token = await self._token(key, timeout_s)
        try:
            response = await self._request(
                "GET",
                key,
                f"{self._chat_base(profile)}/balance",
                headers={"Authorization": f"Bearer {token}"},
                timeout=request_timeout(timeout_s),
            )
        except httpx.TimeoutException:
            raise ProviderError("timeout", "balance: deadline исчерпан") from None
        except httpx.HTTPError:
            raise ProviderError("network", "balance: транспорт недоступен") from None
        if response.status_code == 429:
            raise ProviderError(
                "rate_limit", "balance: HTTP 429", retry_after_s=retry_after(response.headers.get("Retry-After"))
            )
        if response.status_code in (401, 403):
            # 403 also means pay-as-you-go without package balance, not an invalid key.
            raise ProviderError(
                "auth" if response.status_code == 401 else "quota",
                "balance: доступ к пакетам не подтверждён",
                status=response.status_code,
            )
        if response.status_code != 200:
            raise ProviderError("unavailable", f"balance: HTTP {response.status_code}")
        try:
            body = response.json()
        except ValueError:
            raise ProviderError("bad_output", "balance: некорректный JSON") from None
        reject_reflection(body, [key.secret, token])
        return parse_balance(body)

    async def _check_provider_balance(self, scope: accounting.KeyScope, key: ApiKey, profile: LLMProfile) -> None:
        if self.accounting.durable and await scope.uses_provider_balance():
            balances = await scope.wait(
                self.fetch_balance(key, profile, timeout_s=max(0.01, scope.deadline - time.monotonic()))
            )
            require_balance(balances, profile.model)
            scope.provider_balance_verified = True

    async def _chat(
        self, key: ApiKey, payload: dict[str, Any], profile: LLMProfile, timeout_s: float
    ) -> httpx.Response:
        facts = accounting.KeyFacts(self.name, key.secret, self._chat_base(profile), key.tokens_limit, db_id=key.db_id)
        async with self.accounting.key_scope(profile, facts, timeout_s=timeout_s) as scope:
            # OAuth and slot waiting do not consume inference RPD. Unknown quota
            # is rejected before either, while reservation is immediately before POST.
            token = await self._token(key, timeout_s)
            async with generation_slot(self.scope):
                await self._check_provider_balance(scope, key, profile)
                try:
                    async with scope.inference() as ticket:
                        response = await self._post_chat(key, token, payload, profile, timeout_s)
                        try:
                            body = response.json()
                        except ValueError:
                            raise ProviderError("bad_output", "chat: некорректный JSON") from None
                        if not isinstance(body, dict) or not isinstance(body.get("usage"), dict):
                            raise ProviderError("bad_output", "расход ответа неизвестен: usage отсутствует")
                        prompt, completion, total = response_token_counts(
                            body["usage"], [key.secret, key.access_token], coerce=True
                        )
                        await ticket.observe(prompt, completion, total_tokens=total, final=True)
                        self.pool.add_usage(key, total)
                        response.extensions["llm_usage_recorded"] = True
                        return response
                except ProviderError as exc:
                    if self.accounting.durable and await scope.uses_provider_balance():
                        raise _InferenceStarted(
                            exc.kind,
                            exc.detail,
                            retry_after_s=exc.retry_after_s,
                            status=exc.status,
                            usage=exc.usage,
                            request_count=exc.request_count,
                        ) from None
                    raise

    async def _post_chat(
        self, key: ApiKey, token: str, payload: dict[str, Any], profile: LLMProfile, timeout_s: float
    ) -> httpx.Response:
        try:
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
            raise ProviderError("timeout", type(e).__name__) from None
        except httpx.HTTPError as e:
            raise ProviderError("network", type(e).__name__) from None
        if r.status_code in (401, 403) or _bad_authorization(r.status_code, r.text):
            key.access_token = None
            if r.status_code == 403 and "quota" in r.text.lower():
                raise ProviderError("quota", "HTTP 403", status=403)
            raise ProviderError("auth", f"HTTP {r.status_code}", status=r.status_code)
        if r.status_code == 429:
            raise ProviderError(
                "rate_limit", "HTTP 429", status=429, retry_after_s=retry_after(r.headers.get("Retry-After"))
            )
        if (
            r.status_code == 402
            or (r.status_code == 403 and "quota" in r.text.lower())
            or (r.status_code == 400 and "token" in r.text.lower() and "limit" in r.text.lower())
        ):
            raise ProviderError("quota", f"HTTP {r.status_code}", status=r.status_code)
        if r.status_code >= 400:
            raise ProviderError("unavailable", f"HTTP {r.status_code}", status=r.status_code)
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
            except TimeoutError:
                raise ProviderError("timeout", "бюджет запроса исчерпан") from None
            except ProviderError as e:
                if not isinstance(e, accounting.AdmissionRefused):
                    self.pool.mark_error(key, e)
                # Structured inference has no streamed output to duplicate. A
                # transport disconnect may try the next key within this deadline;
                # its fresh scope still requires a positive provider balance.
                # Keep the first attempt unknown; never retry an expired timeout.
                if isinstance(e, _InferenceStarted) and e.kind != "network":
                    raise
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
                # Только pick/admission ДО _chat доказывает отсутствие HTTP и0tokens.
                # Начавшийся wire без validated usage остаётся unknown; per-key
                # прежние known observations при этом сохранены.
                exc.usage = total_usage if total_usage.request_count == 0 else None
                exc.request_count = total_usage.request_count
                raise
            try:
                body = r.json()
            except ValueError:
                raise ProviderError("bad_output", "chat: некорректный JSON") from None
            if not isinstance(body, dict):
                raise ProviderError("bad_output", "chat: ожидается JSON object")
            prompt, completion, total = response_token_counts(
                body.get("usage"), [key.secret, key.access_token], coerce=True
            )
            total_usage.prompt_tokens += prompt
            total_usage.completion_tokens += completion
            total_usage.key_label = key.label
            if not r.extensions.get("llm_usage_recorded"):
                self.pool.add_usage(key, total)
            raw = body["choices"][0]["message"]["content"]
            try:
                obj = extract_json(raw)
                errors = validate_schema(obj, schema, with_constraints=True)
            except ProviderError as e:
                errors = [e.detail]
                obj = {}
            try:
                reject_reflection([raw, obj], [key.secret, key.access_token])
                if body.get("model") != profile.model:
                    reject_reflection(body.get("model"), [key.secret, key.access_token])
            except ProviderError as exc:
                total_usage.cost_rub = profile.cost(total_usage.prompt_tokens, total_usage.completion_tokens)
                exc.usage = total_usage
                raise
            total_usage.model = str(body.get("model") or profile.model)
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
                    + ". Исправь все перечисленные ошибки, сохрани остальные корректные поля "
                    "и не удаляй обязательные поля. Верни исправленный JSON целиком.",
                },
            ]
        total_usage.latency_ms = int((time.perf_counter() - t0) * 1000)
        total_usage.structured_retries = max(0, total_usage.request_count - 1)
        total_usage.cost_rub = profile.cost(total_usage.prompt_tokens, total_usage.completion_tokens)
        raise ProviderError("bad_output", "ответ не соответствует схеме после попыток исправления", usage=total_usage)

    @asynccontextmanager
    async def _stream_key_scope(
        self, profile: LLMProfile, timeout_s: float
    ) -> AsyncIterator[tuple[accounting.KeyScope, ApiKey, str]]:
        """Rotate only during preflight; a started inference is never replayed."""
        deadline = time.monotonic() + timeout_s
        tried: set[str] = set()
        last: ProviderError | None = None
        while True:
            try:
                key = self.pool.pick(exclude=tried)
            except ProviderError as exc:
                raise last or exc from None
            handed_over = False
            try:
                facts = accounting.KeyFacts(
                    self.name, key.secret, self._chat_base(profile), key.tokens_limit, db_id=key.db_id
                )
                async with AsyncExitStack() as stack:
                    scope = await stack.enter_async_context(
                        self.accounting.key_scope(
                            profile, facts, timeout_s=max(0.0, deadline - time.monotonic()), streaming=True
                        )
                    )
                    token = await scope.wait(self._token(key, max(0.0, deadline - time.monotonic())))
                    await scope.wait(stack.enter_async_context(generation_slot(self.scope)))
                    await self._check_provider_balance(scope, key, profile)
                    handed_over = True
                    yield scope, key, token
                    return
            except ProviderError as exc:
                if handed_over:
                    raise
                if not isinstance(exc, accounting.AdmissionRefused):
                    self.pool.mark_error(key, exc)
                tried.add(key.label)
                last = exc
                if (
                    exc.kind not in ("rate_limit", "quota", "auth", "timeout", "network")
                    or time.monotonic() >= deadline
                ):
                    raise

    async def stream(self, messages: list[Message], profile: LLMProfile, *, timeout_s: float) -> AsyncIterator[str]:
        if profile.provider == "openai_compatible":
            raise ProviderError("miss", "профиль openai_compatible")
        async with self._stream_key_scope(profile, timeout_s) as (scope, key, token):
            guard = CredentialStreamGuard([key.secret, token])
            observed: Usage | None = None
            observed_total = 0
            payload = {
                **profile.extra.get("request", {}),
                "model": profile.model,
                "messages": self._ordered(messages),
                "temperature": profile.temperature,
                "stream": True,
            }
            try:
                async with AsyncExitStack() as stream_stack:
                    ticket = await stream_stack.enter_async_context(scope.inference())
                    r = await scope.wait(
                        stream_stack.enter_async_context(
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
                            )
                        )
                    )
                    if r.status_code >= 400:
                        await scope.wait(r.aread())
                        raise ProviderError(
                            "rate_limit" if r.status_code == 429 else "unavailable",
                            f"HTTP {r.status_code}",
                            status=r.status_code,
                        )
                    async for line in scope.iterate(r.aiter_lines()):
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data)
                        except ValueError:
                            raise ProviderError("bad_output", "stream: некорректный JSON", usage=observed) from None
                        if not isinstance(chunk, dict):
                            raise ProviderError("bad_output", "stream: ожидается JSON object", usage=observed)
                        if chunk.get("usage"):
                            prompt, completion, total = response_token_counts(
                                chunk["usage"], [key.secret, token], coerce=True
                            )
                            previous_total = observed_total
                            first_usage = observed is None
                            observed = observe_stream_usage(
                                observed,
                                {"prompt_tokens": prompt, "completion_tokens": completion},
                                profile,
                                self.name,
                                key.label,
                            )
                            await ticket.observe(prompt, completion, total_tokens=total)
                            observed_total = total
                            self.pool.add_usage(key, total - previous_total, request_increment=first_usage)
                        # Usage-only SSE frame может законно иметь choices=[].
                        choices = chunk.get("choices") or []
                        if not isinstance(choices, list) or (choices and not isinstance(choices[0], dict)):
                            raise ProviderError("bad_output", "stream: неверные choices", usage=observed)
                        delta_data = (choices[0].get("delta") or {}) if choices else {}
                        if not isinstance(delta_data, dict):
                            raise ProviderError("bad_output", "stream: неверный delta", usage=observed)
                        delta = delta_data.get("content")
                        if delta is not None and not isinstance(delta, str):
                            raise ProviderError("bad_output", "stream: неверный content", usage=observed)
                        if delta:
                            safe = guard.feed(delta)
                            if safe:
                                yield safe
                    if observed is None:
                        raise ProviderError("bad_output", "расход stream неизвестен: usage отсутствует")
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
            except httpx.TimeoutException as e:
                raise ProviderError("timeout", type(e).__name__, usage=observed) from None
            except httpx.HTTPError as e:
                raise ProviderError("network", type(e).__name__, usage=observed) from None
