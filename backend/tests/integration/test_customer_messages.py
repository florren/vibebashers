"""#137: основной close не раскрывает report; бонус требует доказательства выдачи."""

import psycopg
import pytest

from app.agent.customer_messages import customer_outcome
from app.agent.graph import _restore_recording_state, load_deps
from app.agent.nodes import close
from app.agent.tools.base import ToolContext
from tests.helpers import MOCK_PROFILE, dsn, mock_chain, new_run, run_agent_on, sim_now

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("artifact_kind", ["verification_report", "release_note"])
async def test_agent_close_keeps_report_internal_and_gift_awaits_approval(seeded, artifact_kind):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        rid = await new_run(conn, "customer copy")
        cid = (
            await (
                await conn.execute("select id from clients where segment_code='mass' order by id limit 1")
            ).fetchone()
        )[0]
        sid, state = await run_agent_on(
            conn, "Не открывается вклад в мобильном приложении, ошибка503", client_id=cid, run_id=rid
        )
        iid = (
            await (await conn.execute("select incident_id from incident_signals where signal_id=%s", (sid,))).fetchone()
        )[0]
        report = "На стенде проверен согласованный маршрут. Внешние действия и движение денег не выполнялись."
        await conn.execute("update incidents set resolution_summary=%s,sla_breached=true where id=%s", (report, iid))
        if artifact_kind == "release_note":
            await conn.execute("update incidents set status='closed' where id=%s", (iid,))
        await conn.execute(
            "insert into incident_artifacts(run_id,incident_id,kind,title,body_md,meta,published_sim,generated_by) values (%s,%s,%s,'Проверка',%s,'{\"demo\":true,\"outcome\":\"late\"}',%s,'template')",
            (rid, iid, artifact_kind, report, await sim_now(conn)),
        )
        tid = (
            await (
                await conn.execute(
                    'insert into tasks(run_id,kind,incident_id,client_id,requires_hitl,status,payload,created_sim) values (%s,\'gift\',%s,%s,true,\'open\',\'{"gift":{"gift_code":"bonus_points","points":1000}}\',%s) returning id',
                    (rid, iid, cid, await sim_now(conn)),
                )
            ).fetchone()
        )[0]
        await conn.commit()
        deps = await load_deps(
            conn,
            chain=mock_chain(),
            profile=MOCK_PROFILE,
            run_id=rid,
            agent_run_id=state["agent_run_id"],
            sim_time=await sim_now(conn),
        )
        state["verified"] = True
        await _restore_recording_state(conn, deps)
        await close(state, deps)
        body = (
            await (
                await conn.execute(
                    "select body from notifications where signal_id=%s and template_code='resolved'", (sid,)
                )
            ).fetchone()
        )[0]
        assert "устранена" in body and "больше времени" in body
        assert not any(s in body.lower() for s in ("стенд", "маршрут", "демонстрац", "1000", "подарок"))
        assert (await (await conn.execute("select resolution_summary from incidents where id=%s", (iid,))).fetchone())[
            0
        ] == report
        assert (await (await conn.execute("select status from tasks where id=%s", (tid,))).fetchone())[0] == "open"
        ctx = ToolContext(conn, run_id=rid, agent_run_id=state["agent_run_id"], sim_time=await sim_now(conn))
        # Один status=done без записи фактической выдачи не подтверждает бонус.
        await conn.execute("update tasks set status='done' where id=%s", (tid,))
        assert "1000" not in await customer_outcome(ctx, iid, cid, "en", resolved=True, late=True)
        await conn.execute(
            'update tasks set payload=payload || \'{"issued":{"label":"1000 бонусных баллов"}}\'::jsonb where id=%s',
            (tid,),
        )
        assert "1000 bonus points" in await customer_outcome(ctx, iid, cid, "en", resolved=True, late=True)
        assert "1000" not in await customer_outcome(ctx, iid, None, "en", resolved=True, late=True)
        await conn.rollback()


async def test_agent_waits_for_emulated_team_close_without_reopen(seeded, monkeypatch):
    from unittest.mock import AsyncMock

    from app.agent import nodes

    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        rid = await new_run(conn, "team verification order")
        cid = (
            await (
                await conn.execute("select id from clients where segment_code='mass' order by id limit 1")
            ).fetchone()
        )[0]
        sid, state = await run_agent_on(conn, "Не открывается вклад в приложении, ошибка503", client_id=cid, run_id=rid)
        iid = (
            await (await conn.execute("select incident_id from incident_signals where signal_id=%s", (sid,))).fetchone()
        )[0]
        at = await sim_now(conn)
        await conn.execute(
            "update incidents set status='fix_deployed',resolution_summary='Спор о комиссии,1290 ₽' where id=%s", (iid,)
        )
        await conn.execute("update followups set status='fired' where agent_run_id=%s", (state["agent_run_id"],))
        await conn.execute(
            "insert into team_actions(run_id,incident_id,team_code,action,payload,action_sim) values (%s,%s,'team_front','release','{\"demo\":true,\"outcome\":\"on_time\"}',%s)",
            (rid, iid, at),
        )
        await conn.commit()
        deps = await load_deps(
            conn, chain=mock_chain(), profile=MOCK_PROFILE, run_id=rid, agent_run_id=state["agent_run_id"], sim_time=at
        )
        await _restore_recording_state(conn, deps)
        ordinary_check = AsyncMock(return_value={"delivered": True, "evidence": ["fault уже устранён"]})
        monkeypatch.setattr(nodes.rt, "verify_service_delivered", ordinary_check)
        for _ in range(2):
            await nodes.verify(state, deps)
            assert not state["verified"] and state["current_node"] == "followup_monitor"
            assert state.get("reopen_count", 0) == 0
        ordinary_check.assert_not_awaited()
        assert (
            await (
                await conn.execute(
                    "select count(*) from followups where agent_run_id=%s and status='scheduled'",
                    (state["agent_run_id"],),
                )
            ).fetchone()
        )[0] == 1
        assert (await (await conn.execute("select status from incidents where id=%s", (iid,))).fetchone())[
            0
        ] == "fix_deployed"
        assert (
            await (
                await conn.execute(
                    "select count(*) from notifications where signal_id=%s and template_code='resolved'", (sid,)
                )
            ).fetchone()
        )[0] == 0
        report = "Проверка команды завершена: сценарий открытия вклада проходит успешно"
        await conn.execute(
            "insert into incident_artifacts(run_id,incident_id,kind,title,body_md,meta,published_sim,generated_by) values (%s,%s,'verification_report','Проверка',%s,'{\"demo\":true,\"outcome\":\"on_time\"}',%s,'template')",
            (rid, iid, report, at),
        )
        await conn.execute("update incidents set status='verifying' where id=%s", (iid,))
        await nodes.verify(state, deps)
        ordinary_check.assert_not_awaited()
        await conn.execute("update incidents set status='closed',resolution_summary=%s where id=%s", (report, iid))
        await nodes.verify(state, deps)
        assert state["verified"] and state["current_node"] == "gift"
        ordinary_check.assert_awaited_once()
        await nodes.close(state, deps)
        body = (
            await (
                await conn.execute(
                    "select body from notifications where signal_id=%s and template_code='resolved'", (sid,)
                )
            ).fetchone()
        )[0]
        assert "устранена" in body and "1290" not in body and "Проверка команды" not in body
