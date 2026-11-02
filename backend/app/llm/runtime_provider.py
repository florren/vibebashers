"""T-051: выбранный сохранённый credential используется только на своём endpoint.

Не меняет env chain для unbound legacy profiles. Bound HTTP client принадлежит
одному вызову и закрывается даже при timeout/cancellation; budget guard SDK тот же.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import partial
from typing import Any
from weakref import WeakKeyDictionary

import psycopg

from app.config import get_settings
from app.db.session import psycopg_dsn
from app.llm.base import LLMProfile, Message, Provider, Usage
from app.llm.budget import load_openrouter_budget
from app.llm.credentials import CredentialBindingError, validate_binding
from app.llm.gigachat import GigaChatProvider
from app.llm.keys import ApiKey, KeyPool
from app.llm.openai_compat import OpenAICompatProvider

_KEY_STATES: WeakKeyDictionary[asyncio.AbstractEventLoop, dict[str, tuple[ApiKey, dict[str, asyncio.Lock]]]] = (
    WeakKeyDictionary()
)


def clear_runtime_keys() -> None:
    """Вызывать после drain акторов: разрывает и возможные loop→Lock→loop ссылки."""
    states = _KEY_STATES.pop(asyncio.get_running_loop(), None)
    if states is not None:
        states.clear()


def _key_state(item: dict[str, Any]) -> tuple[ApiKey, dict[str, asyncio.Lock]]:
    """Сохраняет прежние in-memory Giga health/usage; durable admission — отдельная T-050."""
    states = _KEY_STATES.setdefault(asyncio.get_running_loop(), {})
    identity = str(item["_credential_uid"])
    if identity not in states:
        states[identity] = (
            ApiKey(
                label=f"gigachat_db_{item['id']}",
                secret=item["_secret"],
                db_id=item["id"],
                tokens_limit=item["tokens_limit"],
                tokens_used=item["tokens_used"],
            ),
            {},
        )
    key, locks = states[identity]
    if key.secret != item["_secret"]:
        raise CredentialBindingError(409, "Private credential identity не соответствует сохранённому значению")
    key.tokens_used = max(key.tokens_used, item["tokens_used"])
    key.tokens_limit = item["tokens_limit"]
    return key, locks


class BoundPlaceholder:
    """Выбранный provider разрешён в LLM_CHAIN, но env credential для него нет."""

    durable_accounting = True

    def __init__(self, name: str) -> None:
        self.name = name

    async def complete_structured(
        self, messages: list[Message], schema: dict[str, Any], profile: LLMProfile, *, timeout_s: float
    ) -> tuple[dict[str, Any], Usage, str]:
        raise CredentialBindingError(409, "Для provider требуется явная credential binding")

    def stream(self, messages: list[Message], profile: LLMProfile, *, timeout_s: float) -> AsyncIterator[str]:
        raise CredentialBindingError(409, "Для provider требуется явная credential binding")


@asynccontextmanager
async def selected_provider(
    fallback: Provider, profile: LLMProfile, *, transport: Any = None
) -> AsyncIterator[Provider]:
    if profile.api_key_id is None or fallback.name in {"mock", "replay"}:
        yield fallback
        return
    if fallback.name != profile.provider:
        raise CredentialBindingError(409, "Провайдер не соответствует выбранному API-ключу")
    prebound = getattr(fallback, "credential_id", None) == profile.api_key_id
    async with await psycopg.AsyncConnection.connect(psycopg_dsn(), autocommit=True) as conn:
        item = await validate_binding(conn, profile, reveal=not prebound)
    assert item is not None
    if prebound:
        yield fallback
        return
    settings = get_settings()
    base = str(item["endpoint_url"])
    provider: GigaChatProvider | OpenAICompatProvider
    if profile.provider == "gigachat":
        key, token_locks = _key_state(item)
        provider = GigaChatProvider(
            KeyPool([key]),
            oauth_url=settings.gigachat_oauth_url,
            base_url=base,
            scope=str(item["scope"]),
            verify_ssl=True,
            ca_bundle_file=settings.gigachat_ca_bundle_file,
            transport=transport,
        )
        provider._token_locks = token_locks
    elif profile.provider == "openai_compatible":
        provider = OpenAICompatProvider(
            item["_secret"],
            base,
            endpoint_keys={base: item["_secret"]},
            transport=transport,
            budget_usd=settings.openrouter_budget_usd,
            budget_loader=partial(load_openrouter_budget, settings.openrouter_budget_usd),
            http_referer=f"http://localhost:{settings.app_port}",
        )
    else:
        raise CredentialBindingError(409, "Выбранный API-ключ не имеет live provider")
    try:
        yield provider
    finally:
        await provider.aclose()
