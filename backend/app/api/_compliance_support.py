"""Общее для роутеров ingest/compliance: контекст запуска, фоновые анализы транскриптов."""

from __future__ import annotations

import datetime as dt
from typing import Any

import psycopg
from fastapi import Request

from app.api.common import fetch_one, resolve_run_id
from app.compliance.transcripts import analyze_transcript
from app.config import get_settings
from app.db.session import psycopg_dsn
from app.logging import get_logger
from app.sim.runs import ensure_live_run

log = get_logger(__name__)


async def run_context(request: Request, conn: psycopg.AsyncConnection[dict[str, Any]]) -> tuple[int, dt.datetime]:
    """Текущий запуск и сим-время (из симулятора, иначе из sim_state)."""
    sim = getattr(request.app.state, "sim", None)
    rid = await resolve_run_id(conn, None)
    if rid is None:
        if sim is not None:
            rid = await sim.ensure_live_run()
        else:
            async with conn.transaction():
                rid = await ensure_live_run(conn)
    if sim is not None:
        return int(rid), sim.clock.sim_time
    row = await fetch_one(conn, "select sim_time, current_run_id from sim_state where id = 1")
    if not row or not (rid or row["current_run_id"]):
        raise RuntimeError("нет активного запуска эмуляции")
    return int(rid or row["current_run_id"]), row["sim_time"]


async def analyze_in_background(request: Request, transcript_id: int, *, pacing_delay_s: float = 0.0) -> dict[str, Any]:
    """Отдельное соединение; сигнал клиента отдаём AgentService, если он поднят."""
    app = request.app
    s = get_settings()
    agent = getattr(app.state, "agent", None)
    sim = getattr(app.state, "sim", None)

    async def submit(signal_id: int) -> None:
        if agent is not None:
            agent.submit(signal_id, sim.clock.sim_time if sim else None)

    async with await psycopg.AsyncConnection.connect(psycopg_dsn()) as conn:
        row = await (await conn.execute("select sim_time from sim_state where id = 1")).fetchone()
        sim_time = sim.clock.sim_time if sim else (row[0] if row else dt.datetime.now(dt.UTC))
        return await analyze_transcript(
            conn,
            transcript_id,
            chain=app.state.llm_chain,
            profile=app.state.llm_profile,
            sim_time=sim_time,
            alert_threshold=s.compliance_alert_threshold,
            submit_signal=submit,
            pacing_delay_s=pacing_delay_s,
        )
