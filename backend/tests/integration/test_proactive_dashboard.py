"""Service anchor не является клиентским обращением, raw AR/tokens сохранены."""

import psycopg
import pytest

from app.analytics.dashboard import dashboard
from app.ingest.normalizer import create_signal, from_api_signal
from tests.helpers import dsn

from .test_proactive_recovery import prepare


@pytest.mark.asyncio
async def test_customer_dashboard_excludes_service_but_keeps_incident_economics_and_raw_runs(seeded):
    async with await psycopg.AsyncConnection.connect(dsn(seeded)) as conn:
        run, fid, sid, people, at, state, totals = await prepare(conn)
        before = await (
            await conn.execute("select to_jsonb(e) from incident_economics e where run_id=%s", (run,))
        ).fetchall()
        result = await dashboard(conn, rid=run, refresh_economics=False)
        assert result["signals_total"] == result["signals_today"] == 0
        assert result["critical_total"] == result["repeat_signals_share"] == 0
        assert result["agent_runs"] == 1 and result["tokens_total"] == totals[0] > 0
        assert result["incidents_total"] == 1
        assert result["economics"]["potential_loss_rub"] > 0
        assert result["first_response_by_segment"] == {}
        assert (
            await (
                await conn.execute("select to_jsonb(e) from incident_economics e where run_id=%s", (run,))
            ).fetchall()
            == before
        )
        # Existing external channel=proactive с обычным origin=api остаётся
        # customer input; запрет относится к reserved internal origin/source.
        msg = from_api_signal(
            {"channel_code": "proactive", "text": "Подскажите, как долго ждать восстановления уведомлений?"}
        )
        await create_signal(conn, msg, source_code="api", run_id=run, sim_time=at)
        with_customer = await dashboard(conn, rid=run, refresh_economics=False)
        assert with_customer["signals_total"] == with_customer["signals_today"] == 1
        assert with_customer["agent_runs"] == 1 and with_customer["tokens_total"] == totals[0]
        assert with_customer["incidents_total"] == 1
