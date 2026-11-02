"""Снимок main/fast/twin на AgentRun; SimRun metadata и явный initial main override."""

from __future__ import annotations

import copy
import dataclasses
import math
from typing import Any
from urllib.parse import parse_qsl, urlsplit

import psycopg
from psycopg.rows import dict_row

from app.config import get_settings
from app.llm import credentials
from app.llm.base import LLMProfile
from app.llm.failover import ProviderChain
from app.llm.roles import Role, select
from app.llm.runtime_provider import BoundPlaceholder

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
    credentials.safe_options(values)
    if profile.base_url:
        parsed = urlsplit(profile.base_url)
        if parsed.username or parsed.password or any(key.lower() in SECRET_KEYS for key, _ in parse_qsl(parsed.query)):
            raise ValueError("URL профиля не должен содержать credentials")
        credentials.endpoint(profile.base_url)
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
        if not check_settings and default is not None and default.provider == "mock":
            return {role: dataclasses.replace(default, role=role) for role in ROLES}
        return {role: LLMProfile(code="mock", provider="mock", model="mock-rules-v1", role=role) for role in ROLES}
    if "replay" in modes:
        return {role: dataclasses.replace(profiles[role], provider="replay") for role in ROLES}
    return profiles


def no_llm_snapshot() -> dict[str, Any]:
    """Детерминированный trace не притворяется исполнением выбранной модели."""
    return {"version": 1, "provenance": "no_llm_execution", "roles": {}, "profile_ids": {}, "execution_role": None}


def _forced(profiles: dict[str, LLMProfile], chain: ProviderChain | None = None) -> dict[str, LLMProfile]:
    """Только explicit runtime policy; provider одной роли не меняет остальные роли."""
    configured = get_settings().llm_provider
    mode = configured if configured in {"mock", "replay"} else getattr(chain, "offline_mode", None)
    if mode in {"mock", "replay"}:
        return {role: dataclasses.replace(profile, provider=mode) for role, profile in profiles.items()}
    return profiles


async def capture(
    conn: psycopg.AsyncConnection[Any], main_profile_id: int | None, *, frozen_main: dict[str, Any] | None = None
) -> dict[str, Any]:
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
    if frozen_main is not None:
        selected.pop("main_profile_id", None)
    for profile_id in selected.values():
        if profile_id is not None and (type(profile_id) is not int or profile_id < 1):
            raise ValueError("ID профиля должен быть положительным целым числом")
        await validate_main_profile(conn, profile_id)
        if profile_id is not None:
            source = next(item for item in rows if item["id"] == profile_id)
            values = {key: source[key] for key in LLMProfile.__dataclass_fields__ if key in source}
            await credentials.validate_binding(conn, LLMProfile(**values))
    profiles = select(get_settings(), rows, selected)
    if frozen_main is not None:
        profiles["main"] = LLMProfile(**frozen_main["roles"]["main"])
    for profile in profiles.values():
        if profile.provider not in {"mock", "replay"}:
            await credentials.validate_binding(conn, profile)
    profiles = _forced(profiles)
    by_code = {row["code"]: int(row["id"]) for row in rows}
    profile_ids = {role: by_code.get(profiles[role].code) for role in ROLES}
    if frozen_main is not None:
        profile_ids["main"] = frozen_main["profile_ids"]["main"]
    return {
        "version": 1,
        "explicit_main_override": main_profile_id is not None,
        "roles": {role: _safe(profiles[role]) for role in ROLES},
        "profile_ids": profile_ids,
    }


async def resolve(
    conn: psycopg.AsyncConnection[Any],
    run_id: int,
    chain: ProviderChain,
    default: LLMProfile,
    *,
    agent_run_id: int | None = None,
    new: bool = False,
) -> tuple[ProviderChain, LLMProfile]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("select settings_snapshot from sim_runs where id=%s", (run_id,))
        row = await cur.fetchone()
    run_snapshot = ((row or {}).get("settings_snapshot") or {}).get("llm_profiles")
    snapshot = run_snapshot
    if new:
        async with conn.transaction():
            await conn.execute("select pg_advisory_xact_lock(%s)", (credentials.LOCK,))
            frozen = (
                run_snapshot
                if isinstance(run_snapshot, dict) and run_snapshot.get("explicit_main_override") is True
                else None
            )
            snapshot = await capture(conn, None, frozen_main=frozen)
        if run_snapshot is None and (default.provider in {"mock", "replay"} or chain.offline_mode is not None):
            # Новый AR старого/offline вызывающего кода получает его явные model/tariffs.
            # Это snapshot до исполнения, а не выдуманная история старого AR.
            explicit: dict[str, LLMProfile] = {
                role: dataclasses.replace(chain.profile_for(role, default), role=role) for role in ROLES
            }
            explicit = _offline(explicit, default, chain, check_settings=False)
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute("select id,code from llm_profiles")
                ids_by_code = {item["code"]: item["id"] for item in await cur.fetchall()}
            snapshot = {
                "version": 1,
                "roles": {role: _safe(explicit[role]) for role in ROLES},
                "profile_ids": {role: ids_by_code.get(explicit[role].code) for role in ROLES},
                "provenance": "legacy_explicit_offline_configuration",
            }
        if isinstance(run_snapshot, dict) and run_snapshot.get("explicit_main_override") is True:
            snapshot["provenance"] = "current_roles_with_initial_main_override"
        else:
            snapshot.setdefault("provenance", "current_roles")
    elif agent_run_id is not None:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "select llm_profiles_snapshot from agent_runs where id=%s and sim_run_id=%s", (agent_run_id, run_id)
            )
            saved = await cur.fetchone()
        if saved is None:
            raise ValueError("AgentRun не принадлежит запуску")
        snapshot = saved["llm_profiles_snapshot"]
        if snapshot is None:
            # Авторитетный старый SimRun snapshot допустим только как явно отмеченный legacy source.
            snapshot = run_snapshot
            if snapshot is None and default.provider not in {"mock", "replay"}:
                raise ValueError("Legacy AgentRun не имеет авторитетного snapshot LLM")
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
            if new and profile.provider not in {"mock", "replay"}:
                await credentials.validate_binding(conn, profile)
            profiles[role] = profile
    if snapshot is None:
        profiles = _offline(profiles, default, chain, check_settings=False)
    else:
        profiles = _forced(profiles, chain)
    scoped = copy.copy(chain)
    scoped.providers = chain.provider_source
    if all(profile.provider in {"mock", "replay"} for profile in profiles.values()):
        scoped.providers = [provider for provider in chain.provider_source if provider.name in {"mock", "replay"}]
    allowed = {name.strip() for name in get_settings().llm_chain.split(",")}
    for selected in profiles.values():
        aliases = (
            {selected.provider, "openai_compat", "openrouter"}
            if selected.provider == "openai_compatible"
            else {selected.provider}
        )
        if (
            selected.api_key_id is not None
            and chain.offline_mode is None
            and get_settings().llm_provider not in {"mock", "replay"}
            and selected.provider not in {"mock", "replay"}
            and aliases & allowed
            and selected.provider not in scoped.names
        ):
            scoped.providers = [BoundPlaceholder(selected.provider), *scoped.providers]
    scoped.role_profiles = profiles
    scoped.role_profiles_pinned = snapshot is not None
    scoped.role_snapshot = snapshot
    scoped.role_profile_ids = {
        role: snapshot.get("profile_ids", {}).get(role)
        for role in ROLES
        if snapshot is not None
        and snapshot["roles"][role].get("code") == profiles[role].code
        and snapshot["roles"][role].get("model") == profiles[role].model
    }
    return scoped, profiles["main"]
