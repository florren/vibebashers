"""T-051: единственный writable реестр credential configuration (PGP/APP_SECRET).

Значения секретов доступны только явно private lookup внутри исполнения.
Public projection задаётся положительным списком, включая legacy migration errors.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

import psycopg
from psycopg.rows import dict_row

from app.config import get_settings
from app.errors import Problem
from app.llm import secrets as legacy


class CredentialBindingError(Problem):
    """Невалидная явная привязка не должна превращаться в env failover."""


LOCK = 510013
PUBLIC_FIELDS = (
    "id",
    "provider",
    "label",
    "key_hint",
    "tokens_used",
    "tokens_limit",
    "requests_today",
    "rpd_limit",
    "balance_usd",
    "is_active",
    "last_error",
    "endpoint_url",
    "scope",
    "created_at",
)
PUBLIC_SQL = ",".join(PUBLIC_FIELDS)
SECRET_FIELDS = frozenset(
    {
        "key",
        "api_key",
        "apikey",
        "authorization",
        "password",
        "secret",
        "token",
        "access_token",
        "client_secret",
        "credentials",
        "headers",
        "encrypted_key",
        "key_enc",
        "credential_uid",
    }
)


def public_key(item: dict[str, Any]) -> dict[str, Any]:
    projected = {key: item.get(key) for key in PUBLIC_FIELDS}
    if projected["last_error"]:
        projected["last_error"] = "Ошибка статуса API-ключа"
    return projected


def safe_options(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).casefold() in SECRET_FIELDS:
                raise ValueError("секреты разрешены только в реестре API-ключей")
            safe_options(item)
    elif isinstance(value, list):
        for item in value:
            safe_options(item)


def endpoint(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"https", "http"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        # Query целиком запрещён: opaque названия параметров не доказывают отсутствие credential.
        raise ValueError("endpoint должен быть HTTP(S) URL без credentials, query и fragment")
    return value.rstrip("/")


def default_endpoint(provider: str) -> str:
    settings = get_settings()
    return endpoint(settings.gigachat_base_url if provider == "gigachat" else settings.openrouter_base_url)


async def identity_uid(conn: psycopg.AsyncConnection[Any], provider: str, plain: str) -> Any:
    """Private equality lookup сохраняет identity при alias/delete/re-add; наружу UID не выходит."""
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "select coalesce((select credential_uid from llm_api_keys where provider=%s and pgp_sym_decrypt(encrypted_key,%s)=%s order by id limit 1),gen_random_uuid()) as uid",
            (provider, get_settings().app_secret, plain),
        )
        row = await cur.fetchone()
    assert row is not None
    return row["uid"]


async def migrate_legacy(conn: psycopg.AsyncConnection[Any]) -> None:
    """All-or-nothing enc1→PGP; advisory lock сериализует cutover и config writes.

    Конфликт ID/секрета/провайдера не перенумеровывается. После успешного commit
    legacy settings удалён; при ошибке исходный encrypted payload остаётся целым.
    """
    async with conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("select pg_advisory_xact_lock(%s)", (LOCK,))
        await cur.execute("select value from settings where key='llm_keys' for update")
        old = await cur.fetchone()
        if old is None:
            return
        items = old["value"]
        if not isinstance(items, list):
            raise Problem(409, "Legacy key configuration требует ручной миграции")
        seen: set[int] = set()
        try:
            for item in items:
                kid = item["id"]
                provider = item["provider"]
                if isinstance(kid, bool) or not isinstance(kid, int) or kid <= 0 or kid in seen:
                    raise ValueError("invalid legacy identity")
                if provider not in {"gigachat", "openai_compatible", "mock"}:
                    raise ValueError("invalid legacy provider")
                seen.add(kid)
                plain = legacy.decrypt(item["key_enc"], get_settings().app_secret)
                await cur.execute(
                    "select provider,pgp_sym_decrypt(encrypted_key,%s) as private_plain from llm_api_keys where id=%s for update",
                    (get_settings().app_secret, kid),
                )
                existing = await cur.fetchone()
                if existing:
                    if existing["provider"] != provider or existing["private_plain"] != plain:
                        raise ValueError("legacy identity collision")
                    continue
                await cur.execute(
                    "insert into llm_api_keys(id,provider,label,encrypted_key,key_hint,endpoint_url,scope,tokens_used,tokens_limit,requests_today,requests_day,rpd_limit,balance_usd,is_active,credential_uid) "
                    "overriding system value values(%s,%s,%s,pgp_sym_encrypt(%s,%s),%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        kid,
                        provider,
                        item["label"],
                        plain,
                        get_settings().app_secret,
                        legacy.hint(plain),
                        default_endpoint(provider) if provider != "mock" else None,
                        get_settings().gigachat_scope if provider == "gigachat" else None,
                        int(item.get("tokens_used") or 0),
                        item.get("tokens_limit"),
                        int(item.get("requests_today") or 0),
                        item.get("requests_day"),
                        item.get("rpd_limit"),
                        item.get("balance_usd"),
                        item.get("is_active", True),
                        await identity_uid(conn, provider, plain),
                    ),
                )
        except (KeyError, TypeError, ValueError, psycopg.Error) as exc:
            raise Problem(
                409,
                "Legacy key configuration требует ручной миграции",
                "Конфликт или некорректная encrypted configuration; изменения отменены",
            ) from exc
        # Никогда не уменьшаем sequence после удаления/повторного cutover.
        await cur.execute(
            "select setval(pg_get_serial_sequence('llm_api_keys','id'),greatest("
            "coalesce((select max(id) from llm_api_keys),1),"
            "(select last_value from llm_api_keys_id_seq)),true)"
        )
        await cur.execute("delete from settings where key='llm_keys'")


async def list_keys(conn: psycopg.AsyncConnection[Any], *, reveal: bool = False) -> list[dict[str, Any]]:
    await migrate_legacy(conn)
    async with conn.cursor(row_factory=dict_row) as cur:
        projection = PUBLIC_SQL + (
            ",pgp_sym_decrypt(encrypted_key,%s) as _secret,credential_uid as _credential_uid" if reveal else ""
        )
        await cur.execute(
            f"select {projection} from llm_api_keys where deleted_at is null order by id",
            (get_settings().app_secret,) if reveal else (),
        )
        return list(await cur.fetchall())


async def validate_binding(
    conn: psycopg.AsyncConnection[Any], profile: Any, *, reveal: bool = False
) -> dict[str, Any] | None:
    kid = profile.api_key_id
    if kid is None:
        return None  # Явная совместимость legacy env source, не неявный fallback выбранного ключа.
    if reveal:
        await migrate_legacy(conn)
    async with conn.cursor(row_factory=dict_row) as cur:
        projection = PUBLIC_SQL + (
            ",pgp_sym_decrypt(encrypted_key,%s) as _secret,credential_uid as _credential_uid" if reveal else ""
        )
        await cur.execute(
            f"select {projection} from llm_api_keys where id=%s and deleted_at is null",
            (get_settings().app_secret, kid) if reveal else (kid,),
        )
        item = await cur.fetchone()
    if item is None or not item["is_active"] or item["provider"] != profile.provider:
        raise CredentialBindingError(409, "Выбранный API-ключ отсутствует, неактивен или не соответствует провайдеру")
    if profile.provider == "mock":
        return item
    try:
        actual = endpoint(profile.base_url or default_endpoint(profile.provider))
        bound = endpoint(item["endpoint_url"]) if item["endpoint_url"] else None
    except ValueError as exc:
        raise CredentialBindingError(409, "Выбранный API-ключ имеет некорректную endpoint binding") from exc
    if bound != actual:
        raise CredentialBindingError(409, "Выбранный API-ключ не разрешён для endpoint профиля")
    if profile.provider == "gigachat" and item["scope"] != get_settings().gigachat_scope:
        raise CredentialBindingError(409, "Выбранный API-ключ не соответствует GigaChat scope")
    return item
