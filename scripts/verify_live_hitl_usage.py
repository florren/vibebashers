"""Один live E2E без движения денег: SIG → GigaChat → HITL → продолжение AR.

Создаёт отмеченный синтетический кейс в текущем запуске. Решение тестовое,
use_as_fewshot=false. Сим-часы, настройки и существующие обращения не меняются.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import psycopg
from app.agent.graph import process_signal, resume_after_human
from app.config import get_settings
from app.db.session import psycopg_dsn
from app.ingest.normalizer import create_signal, from_api_signal
from app.llm.failover import build_chain
from app.llm.gigachat import GigaChatProvider
from app.llm.roles import refresh
from psycopg.rows import dict_row


async def totals(conn, arid):
    row = await (
        await conn.execute(
            "select ar.total_tokens,ar.prompt_tokens,ar.completion_tokens,ar.total_latency_ms,ar.cost_estimate,"
            "sum(st.prompt_tokens)::bigint as step_prompt,sum(st.completion_tokens)::bigint as step_completion,"
            "sum(st.latency_ms)::bigint as step_latency from agent_runs ar join agent_steps st on st.run_id=ar.id "
            "where ar.id=%s group by ar.id",
            (arid,),
        )
    ).fetchone()
    return dict(row)


async def main():
    settings = get_settings()
    chain = build_chain(settings)
    app = SimpleNamespace(state=SimpleNamespace(llm_chain=chain))
    await refresh(app, settings, required=True)
    initialization_start = time.perf_counter()
    for provider in chain.providers:
        if isinstance(provider, GigaChatProvider) and not await provider.prepare(
            list(chain.role_profiles.values())
        ):
            raise RuntimeError("Не удалось подготовить GigaChat для live E2E")
    initialization_ms = round((time.perf_counter() - initialization_start) * 1000)
    if app.state.llm_profile.provider != "gigachat":
        raise RuntimeError("Main должен использовать GigaChat")
    try:
        async with await psycopg.AsyncConnection.connect(
            psycopg_dsn(), row_factory=dict_row
        ) as conn:
            current = await (
                await conn.execute(
                    "select current_run_id,sim_time,running from sim_state where id=1"
                )
            ).fetchone()
            if current["running"]:
                raise RuntimeError("Live-проверка требует текущего стенда на паузе")
            rid, now = current["current_run_id"], current["sim_time"]
            if not rid:
                raise RuntimeError("Нужен существующий текущий запуск")
            client = await (
                await conn.execute(
                    "select c.id from clients c where c.is_active and c.segment_code='ultra_vip' and not exists(select 1 from incidents i where i.run_id=%s and i.primary_client_id=c.id) order by c.id limit 1",
                    (rid,),
                )
            ).fetchone()
            if not client:
                raise RuntimeError(
                    "Не найден синтетический клиент для отдельного теста"
                )
            signal = await create_signal(
                conn,
                from_api_signal(
                    {
                        "channel_code": "chat",
                        "client_id": client["id"],
                        "external_id": "live-hitl-usage-" + uuid.uuid4().hex,
                        "text": "В мобильном приложении не открывается выписка по кредитной карте. Вместо PDF появляется ошибка загрузки. Перезагрузка не помогает. Деньги не списывались, прошу проверить отображение выписки.",
                    },
                    origin="jury",
                ),
                source_code="api",
                run_id=rid,
                sim_time=now,
                emit_event=False,
            )
            await conn.commit()
        # Раннер использует tuple-row cursor, как в штатном сервисе.
        async with await psycopg.AsyncConnection.connect(psycopg_dsn()) as conn:
            state = await process_signal(
                conn,
                signal_id=signal["signal_id"],
                chain=chain,
                profile=app.state.llm_profile,
                sim_time=now,
            )
            if state is None or state.get("outcome") != "awaiting_human":
                raise RuntimeError("Ожидался штатный HITL для ultra_vip")
            arid = state["agent_run_id"]
            hd = await (
                await conn.execute(
                    "select id,agent_proposal from human_decisions where agent_run_id=%s and decision is null order by id desc limit 1",
                    (arid,),
                )
            ).fetchone()
            if not hd or hd[1].get("incident_type") == "fee_refund":
                raise RuntimeError("Тест не подтверждает денежное предложение")
            await conn.commit()
        async with await psycopg.AsyncConnection.connect(
            psycopg_dsn(), row_factory=dict_row
        ) as conn:
            before = await totals(conn, arid)
            await conn.execute(
                "update human_decisions set decision='accept',decided_by='codex_e2e',comment='Live-регрессия статистики HITL по запросу пользователя, без движения денег',decided_sim=%s,decided_at=now(),use_as_fewshot=false where id=%s and decision is null",
                (now, hd[0]),
            )
            await conn.commit()
        async with await psycopg.AsyncConnection.connect(psycopg_dsn()) as conn:
            await resume_after_human(
                conn,
                human_decision_id=hd[0],
                chain=chain,
                profile=app.state.llm_profile,
                sim_time=now,
            )
        async with await psycopg.AsyncConnection.connect(
            psycopg_dsn(), row_factory=dict_row
        ) as conn:
            after = await totals(conn, arid)
            assert (
                after["total_tokens"]
                == after["step_prompt"] + after["step_completion"]
                >= before["total_tokens"]
                > 0
            )
            assert (
                after["total_latency_ms"]
                == after["step_latency"]
                >= before["total_latency_ms"]
            )
            assert after["cost_estimate"] >= before["cost_estimate"]
            steps = await (
                await conn.execute(
                    "select node,status,model,latency_ms from agent_steps where run_id=%s order by seq",
                    (arid,),
                )
            ).fetchall()
            llm = [dict(s) for s in steps if s["model"]]
            assert all(
                s["model"].startswith("gigachat:") and s["status"] == "ok" for s in llm
            ), llm
            ledger = await (
                await conn.execute(
                    "select count(*) as n from ledger_entries where agent_run_id=%s",
                    (arid,),
                )
            ).fetchone()
            assert ledger["n"] == 0
            info = await (
                await conn.execute(
                    "select id,incident_id,outcome from agent_runs where id=%s", (arid,)
                )
            ).fetchone()
            result = {
                "signal_id": signal["signal_id"],
                "initialization_ms": initialization_ms,
                "human_decision_id": hd[0],
                "run_id": rid,
                **dict(info),
                "before": before,
                "after": after,
                "llm_steps": llm,
                "ledger_entries": ledger["n"],
            }
            print(json.dumps(result, ensure_ascii=False, default=str))
    finally:
        for provider in chain.providers:
            if close := getattr(provider, "aclose", None):
                await close()


if __name__ == "__main__":
    asyncio.run(main())
