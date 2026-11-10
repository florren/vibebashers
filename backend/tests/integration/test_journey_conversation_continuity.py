"""Один диалог: failed → дополнение со своим контекстом → проверенное восстановление."""

from __future__ import annotations

from datetime import datetime

import psycopg
import pytest
from fastapi import HTTPException
from psycopg.rows import dict_row

from app.agent import nodes
from app.agent.graph import process_signal
from app.agent.runner import AgentService
from app.api.demo_execution import post_demo_recovery
from app.config import get_settings
from app.demo import conversation
from app.demo.execution import complete_manual_followups, manual_cycle
from app.demo.settings import configuration
from app.trace.journey import journey
from tests.helpers import MOCK_PROFILE, dsn, mock_chain
from tests.integration.test_journey_execution_scope import OPTIONS, bank_snapshot, message, send, setup

pytestmark = pytest.mark.integration


async def test_failed_case_retains_context_history_and_recovers_without_new_incident(seeded, monkeypatch):
    app, sim, request = await setup(monkeypatch, seeded)
    svc = app.state.agent = AgentService(mock_chain(), MOCK_PROFILE, dsn=seeded)
    svc.enabled = False
    prompts = []
    original_llm = nodes._llm
    from app.demo import roles

    original_team_reply = roles.respond

    async def team_reply(*args, **kwargs):
        assert not sim._lock.locked(), "Работа команды Journey не должна блокировать часы банка"
        return await original_team_reply(*args, **kwargs)

    monkeypatch.setattr(roles, "respond", team_reply)

    async def followup_llm(deps, task, schema, variables, text, **kwargs):
        obj, meta = await original_llm(deps, task, schema, variables, text, **kwargs)
        if text == "Сколько ещё ждать?":
            if task in ("classify", "decide"):
                prompts.append((task, variables["context"]))
            if task == "classify":
                obj.update(signal_type="info_request", confidence=0.95, product="credit")
            if task == "decide":
                obj["client_action"].update(
                    kind="reply",
                    text_ru="Мы продолжаем работу по вашему обращению о вкладе. Сообщим результат после проверки.",
                )
        return obj, meta

    monkeypatch.setattr(nodes, "_llm", followup_llm)
    try:
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            before = await bank_snapshot(conn)
            cid = (
                await (
                    await conn.execute("select id from clients where segment_code='mass' order by id limit 1")
                ).fetchone()
            )[0]
        root_message = message("case-original-failed")
        root_message["client"] = {"client_id": cid}
        root = await send(request, root_message)
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            state = await process_signal(conn, signal_id=root["signal_id"], chain=svc.chain, profile=svc.profile)
            assert state and state["outcome"] == "deferred"
            rid = state["run_id"]
            iid = (
                await (
                    await conn.execute(
                        "select incident_id from incident_signals where signal_id=%s", (root["signal_id"],)
                    )
                ).fetchone()
            )[0]
            await conn.commit()
            svc.enabled = True
            with pytest.raises(HTTPException) as premature:
                await post_demo_recovery(request, iid)
            assert premature.value.status_code == 409
            svc.enabled = False
            for _ in range(10):
                await manual_cycle(app, conn, rid, await configuration(conn, rid))
                await conn.commit()
            assert (await (await conn.execute("select status from incidents where id=%s", (iid,))).fetchone())[
                0
            ] == "escalated"
            previous_actions = await (
                await conn.execute("select id from team_actions where incident_id=%s order by id", (iid,))
            ).fetchall()
            original_problem = await (
                await conn.execute("select team_code,priority,title,problem_summary from incidents where id=%s", (iid,))
            ).fetchone()
            await conn.execute(
                "update notifications set status='queued' where incident_id=%s and template_code='demo_unresolved'",
                (iid,),
            )
            await conn.commit()
            svc.enabled = True
            with pytest.raises(HTTPException) as undelivered:
                await post_demo_recovery(request, iid)
            assert undelivered.value.status_code == 409
            svc.enabled = False
            await conn.execute(
                "update notifications set status='sent' where incident_id=%s and template_code='demo_unresolved'",
                (iid,),
            )
            await conn.commit()
        other_message = message("separate-case-same-customer")
        other_message["client"] = {"client_id": cid}
        other_message["text"] = "Другой независимый вопрос по кредитной карте"
        other = await send(request, other_message)
        child_message = message("case-status-followup", parent=root["signal_id"])
        child_message["meta"] = {"parent_signal_id": root["signal_id"]}
        child_message["client"] = {"client_id": cid}
        child_message["text"] = "Сколько ещё ждать?"
        child = await send(request, child_message)
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            child_state = await process_signal(conn, signal_id=child["signal_id"], chain=svc.chain, profile=svc.profile)
            assert child_state and child_state["outcome"] == "deferred"
            assert child_state["classification"]["product"] == "deposit"
            assert child_state["decision"]["incident_action"] == "link_existing"
            assert child_state["decision"]["link_incident_id"] == iid
            assert child_state["decision"]["router_action"] == "none"
            assert (
                await (
                    await conn.execute(
                        "select incident_id from notifications where signal_id=%s and template_code='ack_received'",
                        (child["signal_id"],),
                    )
                ).fetchone()
            )[0] == iid
            assert (
                await (
                    await conn.execute(
                        "select team_code,priority,title,problem_summary from incidents where id=%s", (iid,)
                    )
                ).fetchone()
            ) == original_problem
            assert {row["id"] for row in await conversation.messages(conn, child["signal_id"], rid)} == {
                root["signal_id"],
                child["signal_id"],
            }
            assert other["signal_id"] not in {
                row["id"] for row in await conversation.messages(conn, child["signal_id"], rid)
            }
            await conn.commit()
        assert len(prompts) == 2
        for _, context in prompts:
            assert context["conversation"][0]["user"] == root_message["text"]
            assert context["conversation"][0]["agent"]
            assert context["case_incident"]["incident_id"] == iid
            assert context["case_incident"]["product"] == "deposit"
        async with await psycopg.AsyncConnection.connect(dsn(seeded), row_factory=dict_row) as conn:
            model = await journey(conn, f"SIG-{child['signal_id']:06d}", "all")
            assert model["subject"]["ref"] == f"SIG-{child['signal_id']:06d}"
            assert any("не удалось устранить" in m["text_ru"] for m in model["client_lane"])
            assert any(
                m["text_ru"] == child_state["decision"]["client_action"]["text_ru"] for m in model["client_lane"]
            )
        svc.enabled = True
        await post_demo_recovery(request, iid)
        await post_demo_recovery(request, iid)
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            for _ in range(10):
                await manual_cycle(app, conn, rid, await configuration(conn, rid))
                await conn.commit()
                await complete_manual_followups(app, conn, rid)
                await conn.commit()
            assert (await (await conn.execute("select count(*) from incidents where run_id=%s", (rid,))).fetchone())[
                0
            ] == 1
            assert (await (await conn.execute("select status from incidents where id=%s", (iid,))).fetchone())[
                0
            ] == "closed"
            assert (
                await (
                    await conn.execute(
                        "select id from team_actions where incident_id=%s and payload->>'outcome'='failed' order by id",
                        (iid,),
                    )
                ).fetchall()
            ) == previous_actions
            assert (
                await (
                    await conn.execute(
                        "select count(*) from team_actions where incident_id=%s and action='fix_decision' and payload->>'outcome'='recovered'",
                        (iid,),
                    )
                ).fetchone()
            )[0] == 1
            notices = await (
                await conn.execute(
                    "select template_code,sent_sim from notifications where incident_id=%s and template_code in ('demo_unresolved','resolved') order by sent_at,id",
                    (iid,),
                )
            ).fetchall()
            assert [row[0] for row in notices] == ["demo_unresolved", "resolved"]
            assert notices[0][1] <= notices[1][1]
            assert (
                await (
                    await conn.execute(
                        "select signal_id from notifications where incident_id=%s and template_code='resolved'", (iid,)
                    )
                ).fetchone()
            )[0] == child["signal_id"]
            settled_runs = (
                await (await conn.execute("select count(*) from agent_runs where sim_run_id=%s", (rid,))).fetchone()
            )[0]
            await manual_cycle(app, conn, rid, await configuration(conn, rid))
            await conn.commit()
            assert (
                await (await conn.execute("select count(*) from agent_runs where sim_run_id=%s", (rid,))).fetchone()
            )[0] == settled_runs
            assert (await configuration(conn, rid))["team_outcome"] == "failed"
            assert await bank_snapshot(conn) == before
        async with await psycopg.AsyncConnection.connect(dsn(seeded), row_factory=dict_row) as conn:
            model = await journey(conn, f"SIG-{child['signal_id']:06d}", "all")
            at = [datetime.fromisoformat(m["delivered_at"]) for m in model["client_lane"]]
            assert at == sorted(at)
            assert "устранена" in model["client_lane"][-1]["text_ru"]
    finally:
        await svc.stop()
        await sim.shutdown()
        get_settings.cache_clear()


async def test_recovery_cannot_be_a_new_journey_case(seeded, monkeypatch):
    app, sim, request = await setup(monkeypatch, seeded)
    try:
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            before = await bank_snapshot(conn)
        with pytest.raises(HTTPException) as rejected:
            await send(
                request, message("invalid-standalone-recovery", options={**OPTIONS, "team_outcome": "recovered"})
            )
        assert rejected.value.status_code == 422
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
            assert await bank_snapshot(conn) == before
            assert (
                await (
                    await conn.execute(
                        "select count(*) from sim_runs where settings_snapshot->>'created_by'='journey_demo'"
                    )
                ).fetchone()
            )[0] == 0
    finally:
        await sim.shutdown()
        get_settings.cache_clear()
