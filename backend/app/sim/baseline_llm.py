"""T-040: только opaque fingerprint LLM-конфигурации, без сохранения секретов."""

from __future__ import annotations

import hashlib
import json
from typing import Any

LEGACY_PRESENT_SQL = (
    "select exists(select 1 from settings where key='llm_keys' and value not in ('[]'::jsonb,'null'::jsonb))"
)
LEGACY_PENDING = (
    "Реестр LLM-ключей ещё не конвертирован. Откройте реестр API-ключей для transactional cutover "
    "или выполните согласованную конвертацию; baseline не изменён"
)
PROFILES_SQL = (
    "select coalesce(jsonb_agg(to_jsonb(p)-'created_at'-'updated_at' order by p.id),'[]'::jsonb),"
    f"({LEGACY_PRESENT_SQL}) from llm_profiles p"
)
KEYS_SQL = "select id,provider,label,is_active,tokens_limit,rpd_limit,endpoint_url,scope,credential_uid::text,(deleted_at is not null),encrypted_key from llm_api_keys order by id"
SETUP_SQL = "select value->'llm' from settings where key='setup_payload'"


class LLMConfigDrift(ValueError):
    pass


def fingerprint(profiles: Any, keys: list[Any], setup: Any) -> str:
    if not isinstance(profiles, list) or (setup is not None and not isinstance(setup, dict)):
        raise LLMConfigDrift("Неверная структура LLM-конфигурации; восстановление не начато")
    protected = []
    for *metadata, encrypted in keys:
        if not isinstance(encrypted, bytes | memoryview):
            raise LLMConfigDrift("Ключи должны использовать существующее encrypted DB хранилище")
        protected.append([*metadata, hashlib.sha256(bytes(encrypted)).hexdigest()])
    data = {
        "profiles": sorted(profiles, key=lambda row: row["id"]),
        "keys": sorted(protected, key=lambda row: row[0]),
        "setup_llm": setup or {},
    }
    encoded = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


async def ensure_canonical(conn: Any) -> None:
    """Только boolean metadata: не читаем/decrypt/конвертируем legacy credential values."""
    row = await (await conn.execute(LEGACY_PRESENT_SQL)).fetchone()
    if row and row[0] is True:
        raise LLMConfigDrift(LEGACY_PENDING)


def read_sync(cur: Any) -> str:
    row = cur.execute(PROFILES_SQL).fetchone()
    if len(row) > 1 and row[1] is True:
        raise LLMConfigDrift(LEGACY_PENDING)
    profiles = row[0]
    keys = cur.execute(KEYS_SQL).fetchall()
    setup = cur.execute(SETUP_SQL).fetchone()
    return fingerprint(profiles, keys, setup[0] if setup else None)


async def read(conn: Any) -> str:
    row = await (await conn.execute(PROFILES_SQL)).fetchone()
    if len(row) > 1 and row[1] is True:
        raise LLMConfigDrift(LEGACY_PENDING)
    profiles = row[0]
    keys = await (await conn.execute(KEYS_SQL)).fetchall()
    setup = await (await conn.execute(SETUP_SQL)).fetchone()
    return fingerprint(profiles, keys, setup[0] if setup else None)


def validate(meta: dict[str, Any], actual: str, dump_sha: str) -> None:
    expected = meta.get("llm_config_fingerprint")
    if not isinstance(expected, str) or len(expected) != 64 or meta.get("dump_sha256") != dump_sha:
        raise LLMConfigDrift(
            "Снимок baseline не подтверждает LLM-конфигурацию. Пересоздайте снимок через существующий baseline dump/prepare и повторите restore; данные не менялись"
        )
    if expected != actual:
        raise LLMConfigDrift(
            "LLM-каталог, ключи или настройки ролей изменились после снимка. Пересоздайте совместимый baseline и повторите restore; текущая конфигурация сохранена"
        )
