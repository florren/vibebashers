"""Общий выбор main/fast/twin из мастера; явный mock/replay исключает живые вызовы."""

from __future__ import annotations

import dataclasses
from typing import Any, Literal

import psycopg
from psycopg.rows import dict_row

from app.config import Settings, get_settings
from app.db.session import psycopg_dsn
from app.errors import Problem
from app.llm.base import LLMProfile
from app.llm.failover import default_profile
from app.logging import get_logger

log = get_logger(__name__)
Role = Literal["main", "fast", "twin"]
ROLES: dict[Role, str] = {"main": "GigaChat-3-Ultra", "fast": "GigaChat-3-Lightning", "twin": "GigaChat-3-Pro"}


def select(settings: Settings, rows: list[dict[str, Any]], selected: dict[str, Any]) -> dict[str, LLMProfile]:
    fallback = default_profile(settings)
    result: dict[str, LLMProfile] = {}
    for role, model in ROLES.items():
        pid = selected.get(f"{role}_profile_id")
        candidates = [r for r in rows if r["is_active"] and (r["id"] == pid if pid else r["role"] == role)]
        if pid and not candidates:
            raise Problem(422, f"Выбранный профиль {role} отсутствует или неактивен")
        provider = "openai_compatible" if settings.llm_provider == "openai_compat" else settings.llm_provider
        if not pid and settings.llm_provider not in ("mock", "replay"):
            candidates = [r for r in candidates if r["provider"] == provider]
        preferred = sorted(candidates, key=lambda r: (r["provider"] != provider, r["id"]))
        if preferred:
            values = {k: preferred[0][k] for k in LLMProfile.__dataclass_fields__ if k in preferred[0]}
            for key in ("temperature", "price_in_per_1m", "price_out_per_1m"):
                if key in values:
                    values[key] = float(values[key])
            profile = LLMProfile(**values)
        elif settings.llm_provider == "gigachat":
            profile = dataclasses.replace(fallback, code=f"gigachat_{role}", model=model)
        else:
            profile = fallback
        if settings.llm_provider in ("mock", "replay"):
            profile = dataclasses.replace(profile, provider=settings.llm_provider)
            if settings.llm_provider == "mock":
                profile = dataclasses.replace(fallback, role=role)
        result[role] = dataclasses.replace(profile, role=role)
    return result


async def refresh(app: Any, settings: Settings | None = None, *, required: bool = False) -> None:
    settings = settings or get_settings()
    try:
        if settings.llm_provider == "mock":
            profiles = select(settings, [], {})
            _apply(app, profiles)
            return
        async with await psycopg.AsyncConnection.connect(
            psycopg_dsn(), row_factory=dict_row, connect_timeout=3
        ) as conn:
            rows = list(await (await conn.execute("select * from llm_profiles order by id")).fetchall())
            row = await (await conn.execute("select value from settings where key='setup_payload'")).fetchone()
            selected = ((row or {}).get("value") or {}).get("llm") or {}
        profiles = select(settings, rows, selected)
    except psycopg.Error as exc:
        if required:
            raise
        log.warning("llm_roles_db_unavailable", error_type=type(exc).__name__)
        profiles = select(settings, [], {})
    _apply(app, profiles)


def _apply(app: Any, profiles: dict[str, LLMProfile]) -> None:
    app.state.llm_chain.role_profiles = profiles
    app.state.llm_profile = profiles["main"]
    app.state.llm_fast_profile = profiles["fast"]
    app.state.llm_twin_profile = profiles["twin"]
    for name in ("agent", "twins"):
        service = getattr(app.state, name, None)
        if service is not None:
            service.chain, service.profile = app.state.llm_chain, profiles["main"]
