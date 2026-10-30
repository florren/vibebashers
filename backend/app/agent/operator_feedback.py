"""T-268: надёжный отдельный разбор поздних сведений, без переисполнения act."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import psycopg

from app.agent import nodes
from app.agent.prompts import prompt_version
from app.agent.tools.base import ToolContext
from app.agent.tools.operator_feedback import apply_operator_feedback
from app.contracts.registry import validate
from app.db.session import psycopg_dsn
from app.llm.base import LLMProfile
from app.llm.failover import ProviderChain
from app.logging import get_logger
from app.sim.events import dumps

log = get_logger(__name__)


async def feedback_context(conn: Any, signal_id: int, run_id: int) -> list[dict[str, Any]]:
    """Обновляется перед следующим решением/продолжением, включая ещё не разобранные сведения."""
    rows = await (
        await conn.execute(
            """with related as (
        select x.incident_id from incident_signals x join incidents i on i.id=x.incident_id where x.signal_id=%s and i.run_id=%s
        union select incident_id from agent_runs where signal_id=%s and sim_run_id=%s and incident_id is not null
        ) select f.id,f.comment,f.recorded_by,f.recorded_at,p.status,p.review
        from hitl_feedback f join human_decisions h on h.id=f.human_decision_id
        left join hitl_feedback_processing p on p.feedback_id=f.id
        where h.sim_run_id=%s and (h.signal_id=%s or h.incident_id in (select incident_id from related)
        or exists(select 1 from incident_signals x where x.signal_id=h.signal_id and x.incident_id in (select incident_id from related)))
        order by f.id desc limit 100""",
            (signal_id, run_id, signal_id, run_id, run_id, signal_id),
        )
    ).fetchall()
    return [
        {
            "id": r[0],
            "comment": r[1],
            "recorded_by": r[2],
            "recorded_at": r[3].isoformat(),
            "status": r[4],
            "review": r[5],
        }
        for r in reversed(rows)
    ]


def planned_priority(context: dict[str, Any], original: int) -> int:
    """Последний применённый разбор повышает срочность следующего плана, но не снижает её."""
    applied = [
        f
        for f in context.get("operator_feedback", [])
        if f.get("status") == "applied" and isinstance(f.get("review"), dict)
    ]
    if not applied:
        return original
    priority = applied[-1]["review"].get("priority")
    return min(original, priority) if isinstance(priority, int) and 1 <= priority <= 4 else original


async def process_feedback(conn: Any, feedback_id: int, chain: ProviderChain, profile: LLMProfile) -> bool:
    # Session-level lock переживает commit перед LLM, но освобождается при падении процесса.
    locked = (await (await conn.execute("select pg_try_advisory_lock(268,%s)", (feedback_id,))).fetchone())[0]
    await conn.commit()
    if not locked:
        return False
    arid: int | None = None
    try:
        row = await (
            await conn.execute(
                """select f.comment,h.signal_id,h.incident_id,h.sim_run_id,h.agent_run_id,p.status,p.attempts,
             coalesce((select sim_time from sim_state where id=1),now()),p.agent_run_id
             from hitl_feedback f join human_decisions h on h.id=f.human_decision_id
             join hitl_feedback_processing p on p.feedback_id=f.id where f.id=%s""",
                (feedback_id,),
            )
        ).fetchone()
        if not row or row[5] == "applied":
            await conn.commit()
            return False
        text, sid, iid, rid, source_ar, _, attempts, sim_time, previous_review = row
        if previous_review:
            await conn.execute(
                "update agent_runs set outcome='failed',finished_at=now(),error='Прерванный разбор дополнения' where id=%s and outcome is null",
                (previous_review,),
            )
        # Источник без инцидента остаётся в контексте сигнала и получит задачу ручного разбора.
        incidents = await (
            await conn.execute(
                """select id,public_id,status,priority,team_code,title from incidents where run_id=%s and
             (id=%s or agent_run_id=%s or id in(select incident_id from incident_signals where signal_id=%s)) order by id""",
                (rid, iid, source_ar, sid),
            )
        ).fetchall()
        completed = await (
            await conn.execute(
                "select node,status,output from agent_steps where run_id=%s and node in ('act','act_instant','gift','close','verify') order by seq",
                (source_ar,),
            )
        ).fetchall()
        arid = (
            await (
                await conn.execute(
                    "insert into agent_runs(kind,sim_run_id,signal_id,incident_id,prompt_version,graph_version,started_sim) values ('operator_review',%s,%s,%s,%s,'operator-feedback-v1',%s) returning id",
                    (rid, sid, iid, prompt_version(), sim_time),
                )
            ).fetchone()
        )[0]
        await conn.execute(
            "update hitl_feedback_processing set attempts=%s,agent_run_id=%s,error=null where feedback_id=%s",
            (attempts + 1, arid, feedback_id),
        )
        await conn.commit()
        ctx = ToolContext(conn, run_id=rid, agent_run_id=arid, sim_time=sim_time)
        deps = nodes.Deps(ctx=ctx, chain=chain, profile=profile)
        context = {
            "incidents": [
                {"id": r[0], "code": r[1], "status": r[2], "priority": r[3], "team": r[4], "title": r[5]}
                for r in incidents
            ],
            "completed_actions": [{"node": r[0], "status": r[1], "output": r[2]} for r in completed],
            "operator_feedback": await feedback_context(conn, sid, rid) if sid else [],
        }
        await conn.commit()
        obj, meta = await nodes._llm(deps, "operator_feedback", "agent/operator_feedback", {"context": context}, text)
        errors = validate(obj, "agent/operator_feedback")
        if errors:
            raise ValueError("operator_feedback: " + "; ".join(errors[:2]))
        ctx.llm_source = (
            "mock"
            if meta.get("fallback_mock") or meta.get("provider") == "mock"
            else "replay"
            if meta.get("provider") == "replay"
            else "live"
        )
        # Эффекты и отметка applied коммитятся одной транзакцией; повтор не создаёт новые задачи.
        result = await apply_operator_feedback(ctx, feedback_id, [r[0] for r in incidents], obj, signal_id=sid)
        await deps.record_step(
            "operator_feedback",
            "fallback" if meta.get("fallback_mock") else "ok",
            {"feedback_id": feedback_id, **context},
            {"review": obj, "applied": result},
            prompt=meta.get("prompt"),
            raw=meta.get("raw"),
            model=meta.get("model"),
            usage=meta.get("usage"),
            latency_ms=meta.get("latency_ms", 0),
        )
        await conn.execute(
            "update hitl_feedback_processing set status='applied',review=%s::jsonb,applied_at=now(),error=null where feedback_id=%s",
            (dumps(obj), feedback_id),
        )
        await conn.execute(
            "update agent_runs set outcome='completed',finished_at=now(),total_tokens=%s,prompt_tokens=%s,completion_tokens=%s,total_latency_ms=%s,cost_estimate=%s where id=%s",
            (
                deps.tokens["prompt"] + deps.tokens["completion"],
                deps.tokens["prompt"],
                deps.tokens["completion"],
                deps.tokens["latency_ms"],
                deps.tokens["cost"],
                arid,
            ),
        )
        await ctx.notify("hitl", "feedback_applied", {"feedback_id": feedback_id, "agent_run_id": arid})
        await conn.commit()
        return True
    except Exception as exc:
        await conn.rollback()
        await conn.execute(
            "update hitl_feedback_processing set status='failed',error=%s,retry_at=now()+interval '30 seconds' where feedback_id=%s",
            (type(exc).__name__, feedback_id),
        )
        if arid:
            await conn.execute(
                "update agent_runs set outcome='failed',finished_at=now(),error=%s where id=%s",
                (type(exc).__name__, arid),
            )
        await conn.commit()
        log.warning("operator_feedback_failed", feedback_id=feedback_id, error=type(exc).__name__)
        return False
    finally:
        await conn.execute("select pg_advisory_unlock(268,%s)", (feedback_id,))
        await conn.commit()


async def worker(provider: Callable[[], tuple[ProviderChain, LLMProfile]], dsn: str | None = None) -> None:
    # Независим от занятой очереди исходных сигналов и симуляционных часов/паузы.
    while True:
        try:
            async with await psycopg.AsyncConnection.connect(psycopg_dsn(dsn)) as conn:
                rows = await (
                    await conn.execute(
                        "select feedback_id from hitl_feedback_processing where status<>'applied' and attempts<3 and retry_at<=now() order by feedback_id limit 20"
                    )
                ).fetchall()
                await conn.commit()
                for (fid,) in rows:
                    await process_feedback(conn, int(fid), *provider())
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("operator_feedback_worker_failed", error=type(exc).__name__)
        await asyncio.sleep(2)
