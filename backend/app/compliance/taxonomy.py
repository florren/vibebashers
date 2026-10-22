"""Таксономия паттернов и эталонные скрипты: чтение из БД (проекция data/*.yaml), кэш с инвалидацией по PUT."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import psycopg

_TTL_S = 30.0
_cache: dict[str, tuple[float, Any]] = {}


@dataclass
class Pattern:
    code: str
    family: str
    name_ru: str
    keywords: list[str]
    examples: list[str]
    counter_examples: list[str]
    weight: float
    is_active: bool
    alert_policy: str
    immediate_threshold: float
    recommendation_ru: str | None
    training_module: str | None


@dataclass
class ScriptStep:
    code: str
    name_ru: str
    markers: list[str]
    required: bool = True


@dataclass
class ServiceScript:
    code: str
    kind: str
    steps: list[ScriptStep]
    forbidden_phrases: list[str] = field(default_factory=list)


def invalidate() -> None:
    _cache.clear()


async def load_patterns(conn: psycopg.AsyncConnection[Any], *, only_active: bool = False) -> list[Pattern]:
    key = "patterns"
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < _TTL_S:
        pats: list[Pattern] = hit[1]
    else:
        rows = await (
            await conn.execute(
                "select code, family, name_ru, keywords, examples, counter_examples, weight, is_active, alert_policy, immediate_threshold, recommendation_ru, training_module "
                "from misselling_patterns order by code"
            )
        ).fetchall()
        pats = [
            Pattern(
                code=_c(r, 0),
                family=_c(r, 1),
                name_ru=_c(r, 2),
                keywords=list(_c(r, 3) or []),
                examples=list(_c(r, 4) or []),
                counter_examples=list(_c(r, 5) or []),
                weight=float(_c(r, 6) or 1),
                is_active=bool(_c(r, 7)),
                alert_policy=_c(r, 8),
                immediate_threshold=float(_c(r, 9) or 0.8),
                recommendation_ru=_c(r, 10),
                training_module=_c(r, 11),
            )
            for r in rows
        ]
        _cache[key] = (time.monotonic(), pats)
    return [p for p in pats if p.is_active] if only_active else pats


async def load_script(conn: psycopg.AsyncConnection[Any], kind: str) -> ServiceScript | None:
    """kind: retail_service | contact_center (из service_scripts.kind)."""
    key = f"script:{kind}"
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < _TTL_S:
        return hit[1]  # type: ignore[no-any-return]
    row = await (
        await conn.execute(
            "select code, kind, steps from service_scripts where kind = %s and is_active order by version desc limit 1",
            (kind,),
        )
    ).fetchone()
    if not row:
        return None
    steps_doc = _c(row, 2) or {}
    steps_list = steps_doc.get("steps") if isinstance(steps_doc, dict) else steps_doc
    script = ServiceScript(
        code=_c(row, 0),
        kind=_c(row, 1),
        steps=[
            ScriptStep(
                code=s["code"],
                name_ru=s.get("name_ru") or s["code"],
                markers=list(s.get("markers") or []),
                required=bool(s.get("required", True)),
            )
            for s in (steps_list or [])
        ],
        forbidden_phrases=list((steps_doc.get("forbidden_phrases") if isinstance(steps_doc, dict) else None) or []),
    )
    _cache[key] = (time.monotonic(), script)
    return script


def script_kind_for(transcript_kind: str) -> str:
    return "retail_service" if transcript_kind == "branch_retail" else "contact_center"


def _c(row: Any, i: int) -> Any:
    if isinstance(row, dict):
        return list(row.values())[i]
    return row[i]
