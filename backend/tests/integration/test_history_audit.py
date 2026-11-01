"""#131: безопасный аудит и идемпотентное завершение orphan после отказа."""

import psycopg
import pytest

from app.agent.graph import resume_after_human
from app.agent.tools.base import ToolContext
from app.agent.tools.write import schedule_followup
from app.demo.history import audit, repair_rejected
from tests.helpers import MOCK_PROFILE, dsn, mock_chain, new_run, run_agent_on, sim_now

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("decision", ["reject", "accept"])
async def test_rejected_orphan_repair_is_explicit_and_audited(seeded, decision):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        rid = await new_run(conn, "history repair")
        cid = (
            await (
                await conn.execute("select id from clients where segment_code='ultra_vip' order by id limit 1")
            ).fetchone()
        )[0]
        sid, state = await run_agent_on(
            conn, "Проверьте тариф дебетовой карты, без возврата денег.", client_id=cid, run_id=rid
        )
        arid = state["agent_run_id"]
        await conn.execute("update human_decisions set decision=%s where agent_run_id=%s", (decision, arid))
        if decision == "reject":
            hid = (
                await (
                    await conn.execute(
                        "select id from human_decisions where agent_run_id=%s order by id desc limit 1", (arid,)
                    )
                ).fetchone()
            )[0]
            await conn.commit()
            resumed = await resume_after_human(
                conn, human_decision_id=hid, chain=mock_chain(), profile=MOCK_PROFILE, sim_time=await sim_now(conn)
            )
            assert resumed and resumed["outcome"] == "completed"
            assert (
                await (
                    await conn.execute(
                        "select count(*) from notifications where signal_id=%s and template_code='final_no_action_131' and status='sent'",
                        (sid,),
                    )
                ).fetchone()
            )[0] == 1
            assert (
                await (
                    await conn.execute(
                        "select count(*) from followups where signal_id=%s and status='scheduled'", (sid,)
                    )
                ).fetchone()
            )[0] == 0
        ctx = ToolContext(conn, run_id=rid, agent_run_id=arid, sim_time=await sim_now(conn))
        await schedule_followup(ctx, sid, None, 2, "awaiting_team")
        await conn.execute("update signals set status='deferred' where id=%s", (sid,))
        await conn.execute("update agent_runs set outcome='deferred' where id=%s", (arid,))
        await conn.commit()
        before = await audit(conn, rid)
        assert before["orphan_followups"][0]["signal"] == f"SIG-{sid:06d}"
        assert (await (await conn.execute("select status from signals where id=%s", (sid,))).fetchone())[
            0
        ] == "deferred"
        if decision == "accept":
            with pytest.raises(ValueError, match="нет однозначного"):
                await repair_rejected(conn, sid, rid)
            await conn.rollback()
            assert (
                await (
                    await conn.execute(
                        "select status from followups where signal_id=%s and reason='awaiting_team'", (sid,)
                    )
                ).fetchone()
            )[0] == "scheduled"
        else:
            repaired = await repair_rejected(conn, sid, rid)
            await conn.commit()
            repeat = await repair_rejected(conn, sid, rid)
            await conn.commit()
            assert repeat["deduplicated"] and repeat["agent_run_id"] == repaired["agent_run_id"]
            assert not (await audit(conn, rid))["orphan_followups"]
            assert (
                await (
                    await conn.execute(
                        "select count(*) from notifications where signal_id=%s and template_code='final_no_action_131'",
                        (sid,),
                    )
                ).fetchone()
            )[0] == 1
            assert (
                await (
                    await conn.execute("select count(*) from incident_signals where signal_id=%s", (sid,))
                ).fetchone()
            )[0] == 0
            assert (
                await (
                    await conn.execute("select input from agent_steps where run_id=%s", (repaired["agent_run_id"],))
                ).fetchone()
            )[0]["orphan_followups_before"]


async def test_audit_detects_incompatible_product_in_read_only_transaction(seeded):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        rid = await new_run(conn, "audit old link")
        cid = (
            await (
                await conn.execute("select id from clients where segment_code='mass' order by id limit 1")
            ).fetchone()
        )[0]
        sid, state = await run_agent_on(
            conn, "Не могу открыть вклад в мобильном приложении: ошибка 503", client_id=cid, run_id=rid
        )
        await conn.execute("update incidents set product_code='credit_card' where run_id=%s", (rid,))
        await conn.commit()
        await conn.execute("set transaction read only")
        report = await audit(conn, rid)
        assert any(
            r["signal"] == f"SIG-{sid:06d}"
            and r["incident_product"] == "credit_card"
            and r["signal_product"] == "deposit"
            for r in report["incompatible_links"]
        )
        await conn.rollback()
