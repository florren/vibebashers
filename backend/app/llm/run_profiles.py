"""Снимок main/fast/twin на запуск; общие providers/лимитеры, независимые role bindings."""

from __future__ import annotations

import copy
import dataclasses
import math
from typing import Any
from urllib.parse import parse_qsl, urlsplit

import psycopg
from psycopg.rows import dict_row

from app.config import get_settings
from app.llm.base import LLMProfile
from app.llm.failover import ProviderChain
from app.llm.roles import Role, select

ROLES: tuple[Role, ...] = ("main", "fast", "twin")
SECRET_KEYS = {
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
}


async def validate_main_profile(conn: psycopg.AsyncConnection[Any], profile_id: int | None) -> None:
    if profile_id is None:
        return
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("select is_active,role from llm_profiles where id=%s", (profile_id,))
        row = await cur.fetchone()
    if row is None or not row["is_active"]:
        raise ValueError("профиль LLM отсутствует или неактивен")
    if row["role"] == "bench_only":
        raise ValueError("профиль bench_only доступен только для benchmark и ручного compare")


def _no_secrets(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in SECRET_KEYS:
                raise ValueError("секреты профиля должны храниться через llm_api_keys, не в snapshot")
            _no_secrets(item)
    elif isinstance(value, list):
        for item in value:
            _no_secrets(item)


def _safe(profile: LLMProfile) -> dict[str, Any]:
    if not isinstance(profile.code, str) or not profile.code or not isinstance(profile.model, str) or not profile.model:
        raise ValueError("код и модель профиля должны быть непустыми строками")
    for key in ("temperature", "price_in_per_1m", "price_out_per_1m"):
        value = getattr(profile, key)
        if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
            raise ValueError("числовые настройки профиля должны быть конечными")
        if key.startswith("price_") and value < 0:
            raise ValueError("тариф профиля не может быть отрицательным")
    values = dataclasses.asdict(profile)
    _no_secrets(values)
    if profile.base_url:
        parsed = urlsplit(profile.base_url)
        if parsed.username or parsed.password or any(key.lower() in SECRET_KEYS for key, _ in parse_qsl(parsed.query)):
            raise ValueError("URL профиля не должен содержать credentials")
    return values


def _offline(
    profiles: dict[str, LLMProfile],
    default: LLMProfile | None = None,
    chain: ProviderChain | None = None,
    *,
    check_settings: bool = True,
) -> dict[str, LLMProfile]:
    if (
        not check_settings
        and chain is not None
        and default is not None
        and default.provider != "mock"
        and profiles["main"].provider != "mock"
        and "replay" in chain.names
        and set(chain.names) <= {"replay", "mock"}
    ):
        return {role: dataclasses.replace(profiles[role], provider="replay") for role in ROLES}
    modes: set[str] = {profiles["main"].provider}
    if check_settings:
        modes.add(get_settings().llm_provider)
    if default is not None:
        modes.add(default.provider)
    if "mock" in modes:
        return {role: LLMProfile(code="mock", provider="mock", model="mock-rules-v1", role=role) for role in ROLES}
    if "replay" in modes:
        return {role: dataclasses.replace(profiles[role], provider="replay") for role in ROLES}
    return profiles


async def capture(conn: psycopg.AsyncConnection[Any], main_profile_id: int | None) -> dict[str, Any]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("select * from llm_profiles order by id")
        rows = list(await cur.fetchall())
        await cur.execute("select value from settings where key='setup_payload'")
        row = await cur.fetchone()
    configured = ((row or {}).get("value") or {}).get("llm") or {}
    selected = {
        key: configured[key] for key in ("main_profile_id", "fast_profile_id", "twin_profile_id") if key in configured
    }
    if main_profile_id is not None:
        selected["main_profile_id"] = main_profile_id
    for profile_id in selected.values():
        await validate_main_profile(conn, profile_id)
    profiles = _offline(select(get_settings(), rows, selected))
    by_code = {row["code"]: int(row["id"]) for row in rows}
    return {
        "version": 1,
        "roles": {role: _safe(profiles[role]) for role in ROLES},
        "profile_ids": {role: by_code.get(profiles[role].code) for role in ROLES},
    }


async def resolve(
    conn: psycopg.AsyncConnection[Any], run_id: int, chain: ProviderChain, default: LLMProfile
) -> tuple[ProviderChain, LLMProfile]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("select settings_snapshot from sim_runs where id=%s", (run_id,))
        row = await cur.fetchone()
    snapshot = ((row or {}).get("settings_snapshot") or {}).get("llm_profiles")
    profiles: dict[str, LLMProfile]
    if snapshot is None:
        # Для legacy запуска точный снимок ролей восстановить нельзя. Сохраняем
        # явные bindings вызывающего кода; его mock/replay охватывает все роли.
        profiles = {role: chain.profile_for(role, default) for role in ROLES}
    else:
        if (
            not isinstance(snapshot, dict)
            or snapshot.get("version") != 1
            or set(snapshot.get("roles", {})) != set(ROLES)
        ):
            raise ValueError("неподдерживаемый снимок профилей LLM запуска")
        ids = snapshot.get("profile_ids", {})
        if not isinstance(ids, dict) or any(
            value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 1)
            for value in ids.values()
        ):
            raise ValueError("неверные идентификаторы профилей LLM в снимке запуска")
        profiles = {}
        for role in ROLES:
            values = snapshot["roles"][role]
            if (
                not isinstance(values, dict)
                or values.get("role") != role
                or values.get("provider") not in {"gigachat", "openai_compatible", "mock", "replay"}
            ):
                raise ValueError("неверный профиль LLM в снимке запуска")
            try:
                profile = LLMProfile(**values)
            except TypeError as exc:
                raise ValueError("неверные поля профиля LLM в снимке запуска") from exc
            _safe(profile)
            profiles[role] = profile
    profiles = _offline(profiles, default, chain, check_settings=snapshot is not None)
    scoped = copy.copy(chain)
    if all(profile.provider in {"mock", "replay"} for profile in profiles.values()):
        scoped.providers = [provider for provider in chain.providers if provider.name in {"mock", "replay"}]
    scoped.role_profiles = profiles
    scoped.role_profiles_pinned = snapshot is not None
    scoped.role_profile_ids = {
        role: snapshot.get("profile_ids", {}).get(role)
        for role in ROLES
        if snapshot is not None
        and snapshot["roles"][role].get("code") == profiles[role].code
        and snapshot["roles"][role].get("model") == profiles[role].model
    }
    return scoped, profiles["main"]
