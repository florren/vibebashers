"""#131: аудит исторических связей; явное восстановление ошибочного ожидания после отказа."""

from typing import Any

from app.agent.nodes import Deps
from app.agent.tools.base import ToolContext
from app.agent.tools.write import notify_client
from app.demo.roles import finish_run
from app.i18n import communication_lang, declined_action_text
from app.llm.base import LLMProfile
from app.llm.failover import ProviderChain
from app.llm.mock import MockProvider


async def audit(conn: Any, run_id: int | None, limit: int = 200) -> dict[str, Any]:
    links = await (
        await conn.execute(
            "select s.public_id,i.public_id,s.classification->>'product',i.product_code,s.classification->>'error_code',i.error_code,count(*) over() "
            "from incident_signals x join signals s on s.id=x.signal_id join incidents i on i.id=x.incident_id "
            "where (%s::bigint is null or s.run_id=%s) and (i.run_id<>s.run_id or "
            "(s.classification->>'product' not in ('other','') and i.product_code is not null and s.classification->>'product'<>i.product_code) or "
            "(nullif(s.classification->>'error_code','') is not null and i.error_code is not null and s.classification->>'error_code'<>i.error_code)) order by s.id,i.id limit %s",
            (run_id, run_id, limit),
        )
    ).fetchall()
    orphans = await (
        await conn.execute(
            "select s.public_id,f.id,f.reason,s.status,(select h.decision from human_decisions h where h.agent_run_id=f.agent_run_id order by h.id desc limit 1),count(*) over() "
            "from followups f join signals s on s.id=f.signal_id where f.status='scheduled' and f.incident_id is null "
            "and f.reason in ('awaiting_team','verify_fix','report_due') and (%s::bigint is null or s.run_id=%s) order by f.id limit %s",
            (run_id, run_id, limit),
        )
    ).fetchall()
    return {
        "run_id": run_id,
        "limit": limit,
        "incompatible_links_total": links[0][-1] if links else 0,
        "orphan_followups_total": orphans[0][-1] if orphans else 0,
        "truncated": (links[0][-1] > limit if links else False) or (orphans[0][-1] > limit if orphans else False),
        "incompatible_links": [
            dict(
                zip(
                    ("signal", "incident", "signal_product", "incident_product", "signal_error", "incident_error"),
                    r[:-1],
                    strict=True,
                )
            )
            for r in links
        ],
        "orphan_followups": [
            dict(zip(("signal", "followup_id", "reason", "status", "human_decision"), r[:-1], strict=True))
            for r in orphans
        ],
    }


async def repair_rejected(conn: Any, signal_id: int, run_id: int) -> dict[str, Any]:
    """Только явно выбранный сигнал, ноль связанных инцидентов и подтверждённый отказ человека."""
    await conn.execute("select pg_advisory_xact_lock(hashtext(%s))", (f"history-reject:{signal_id}",))
    version = "history-rejected-followup-131-v1"
    existing = await (
        await conn.execute(
            "select id from agent_runs where signal_id=%s and sim_run_id=%s and prompt_version=%s and outcome='completed'",
            (signal_id, run_id, version),
        )
    ).fetchone()
    if existing:
        return {"agent_run_id": existing[0], "deduplicated": True}
    row = await (
        await conn.execute(
            "select s.client_id,s.channel_code,c.segment_code,c.consents,st.sim_time,s.status,s.text "
            "from signals s left join clients c on c.id=s.client_id cross join sim_state st where s.id=%s and s.run_id=%s and st.id=1 for update of s",
            (signal_id, run_id),
        )
    ).fetchone()
    if row is None:
        raise ValueError("сигнал отсутствует в выбранном запуске")
    linked = await (
        await conn.execute("select 1 from incident_signals where signal_id=%s limit 1", (signal_id,))
    ).fetchone()
    if linked:
        raise ValueError("есть связанный инцидент: нужен отдельный операторский разбор")
    pending = await (
        await conn.execute(
            "select f.id,f.agent_run_id,f.reason,a.outcome,(select h.decision from human_decisions h where h.agent_run_id=f.agent_run_id order by h.id desc limit 1) "
            "from followups f join agent_runs a on a.id=f.agent_run_id where f.signal_id=%s and f.status='scheduled' and f.incident_id is null "
            "and f.reason in ('awaiting_team','verify_fix','report_due') for update of f,a",
            (signal_id,),
        )
    ).fetchall()
    if not pending or any(p[4] != "reject" or p[3] != "deferred" for p in pending):
        raise ValueError("нет однозначного отложенного ожидания после отказа человека")
    arid = (
        await (
            await conn.execute(
                "insert into agent_runs(kind,sim_run_id,signal_id,client_id,prompt_version,graph_version,started_sim) values ('team_emulator',%s,%s,%s,%s,'operator-repair-v1',%s) returning id",
                (run_id, signal_id, row[0], version, row[4]),
            )
        ).fetchone()
    )[0]
    ctx = ToolContext(conn, run_id=run_id, agent_run_id=arid, sim_time=row[4])
    deps = Deps(
        ctx=ctx,
        chain=ProviderChain([MockProvider()]),
        profile=LLMProfile(code="operator_repair", provider="mock", model="operator", role="main"),
    )
    await conn.execute("update followups set status='cancelled' where id=any(%s)", ([p[0] for p in pending],))
    await conn.execute(
        "update agent_runs set outcome='completed',finished_at=now() where id=any(%s)", ([p[1] for p in pending],)
    )
    await conn.execute("update signals set status='closed',updated_at=now() where id=%s", (signal_id,))
    lang = communication_lang(row[6] or "")
    body = declined_action_text(lang)
    notice = await notify_client(
        ctx,
        row[0],
        signal_id,
        None,
        row[1],
        "final_no_action_131",
        {},
        text_override=body,
        lang=lang,
        segment=row[2],
        consents=row[3],
    )
    await deps.record_step(
        "close",
        "ok",
        {"signal_status_before": row[5], "orphan_followups_before": pending, "explicit_operator_repair": True},
        {"notification": notice, "resolution_confirmed": False, "human_rejection_respected": True},
        reasoning="Явное восстановление #131: отменено ошибочное ожидание команды после сохранённого отказа человека. Решение проблемы не заявляется, финансовых действий и подарков нет.",
    )
    await finish_run(conn, arid, {"usage": {}})
    return {
        "agent_run_id": arid,
        "notification_id": notice["notification_id"],
        "cancelled_followups": [p[0] for p in pending],
        "deduplicated": False,
    }
