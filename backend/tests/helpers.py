"""Общие помощники тестов L5 (T-141): прогон агента по тексту, сдвиг сим-времени, проверка событий, запуски.

Используются интеграционными и сценарными тестами; требуют PostgreSQL (фикстура `seeded` из tests/integration/conftest.py).
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import psycopg

from app.agent.graph import process_signal
from app.ingest.normalizer import create_signal, from_api_signal
from app.llm.base import LLMProfile
from app.llm.failover import ProviderChain
from app.llm.mock import MockProvider

MOCK_PROFILE = LLMProfile(code="mock", provider="mock", model="mock-1", role="main")


def dsn(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def mock_chain() -> ProviderChain:
    return ProviderChain([MockProvider()])


async def sim_now(conn: psycopg.AsyncConnection[Any]) -> dt.datetime:
    row = await (await conn.execute("select sim_time from sim_state where id = 1")).fetchone()
    assert row
    return row[0]


async def advance_sim(conn: psycopg.AsyncConnection[Any], hours: float) -> dt.datetime:
    """Сдвигает сим-часы (без запуска цикла симулятора) — для проверок SLA/followup по сим-времени."""
    row = await (
        await conn.execute(
            "update sim_state set sim_time = sim_time + make_interval(secs => %s), updated_at = now() where id = 1 returning sim_time",
            (hours * 3600,),
        )
    ).fetchone()
    await conn.commit()
    assert row
    return row[0]


async def new_run(
    conn: psycopg.AsyncConnection[Any], label: str, kind: str = "scenario", scenario_id: str | None = None
) -> int:
    """Отдельный запуск эмуляции для изоляции данных теста (T-146)."""
    from app.sim import runs as run_svc

    rid = await run_svc.create_run(
        conn, kind=kind, label=label, seed=42, sim_time=await sim_now(conn), scenario_id=scenario_id
    )
    await conn.commit()
    return int(rid)


async def run_agent_on(
    conn: psycopg.AsyncConnection[Any],
    text: str,
    *,
    client_id: int | None,
    channel: str = "chat",
    run_id: int | None = None,
    origin: str = "jury",
) -> tuple[int, dict[str, Any]]:
    """Создаёт сигнал и прогоняет агента на mock-модели. Возвращает (signal_id, state)."""
    body: dict[str, Any] = {"channel_code": channel, "text": text}
    if client_id is not None:
        body["client_id"] = client_id
    else:
        body["external_contact"] = {"nick": "@unknown_tester"}
    msg = from_api_signal(body, origin=origin)
    res = await create_signal(conn, msg, source_code="api", run_id=run_id, emit_event=False)
    await conn.commit()
    assert res["status"] == "accepted", res
    state = await process_signal(conn, signal_id=int(res["signal_id"]), chain=mock_chain(), profile=MOCK_PROFILE)
    assert state is not None
    return int(res["signal_id"]), dict(state)


async def events_of(
    conn: psycopg.AsyncConnection[Any], run_id: int, event_type: str | None = None
) -> list[dict[str, Any]]:
    sql = (
        "select event_type, payload from sim_events where run_id = %s"
        + (" and event_type = %s" if event_type else "")
        + " order by id"
    )
    args: tuple[Any, ...] = (run_id, event_type) if event_type else (run_id,)
    rows = await (await conn.execute(sql, args)).fetchall()
    return [{"type": r[0], **(r[1] or {})} for r in rows]


def assert_event(events: list[dict[str, Any]], event_type: str, **fields: Any) -> dict[str, Any]:
    """Первое событие нужного типа с совпадающими полями payload; иначе AssertionError с перечнем того, что было."""
    for e in events:
        if e.get("type") == event_type and all(e.get(k) == v for k, v in fields.items()):
            return e
    seen = sorted({e.get("type") for e in events})
    raise AssertionError(f"нет события {event_type} {fields or ''}; были типы: {seen}")
