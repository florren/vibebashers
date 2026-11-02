"""T-273: idle/pause без синтетики, явный mock и безопасное восстановление."""

from __future__ import annotations

import asyncio
import datetime as dt
from unittest.mock import AsyncMock, Mock

import psycopg
import pytest
from psycopg.rows import dict_row

from app.agent import graph, runner
from app.agent.runner import AgentService
from app.config import get_settings
from app.ingest.normalizer import create_signal, from_api_signal
from app.ingest.sources import poll_source, polling_worker
from tests.helpers import MOCK_PROFILE, dsn, mock_chain
from tests.integration.test_hitl_continuity import NOW, make_case

pytestmark = pytest.mark.integration


def counts(conn):
    return tuple(
        conn.execute(f"select count(*) from {table}").fetchone()[0]
        for table in ("signals", "sim_events", "external_posts", "agent_runs")
    )


@pytest.mark.parametrize("profile", ["lite", "demo", "stress"])
def test_enabled_mock_sources_do_not_generate_in_idle_or_pause(seeded, conn, monkeypatch, profile):
    monkeypatch.setenv("DATABASE_URL", seeded)
    monkeypatch.setenv("PROFILE", profile)
    get_settings.cache_clear()
    # Legacy-конфигурация enabled=true должна быть безопасна без переустановки справочников.
    conn.execute(
        "update ingest_sources set enabled=true,config='{\"url\":\"http://localhost/mock-social-feed\"}' where code in ('mock_social_polling','review_portal_feed')"
    )

    async def window():
        stop = asyncio.Event()
        task = asyncio.create_task(polling_worker(stop))
        await asyncio.sleep(5.3)
        stop.set()
        await asyncio.wait_for(task, 5)

    try:
        before = counts(conn)
        asyncio.run(window())
        assert counts(conn) == before
        rid = conn.execute(
            "insert into sim_runs(kind,label,seed,started_sim,status) select 'free','paused-probe',seed,sim_time,'paused' from sim_state where id=1 returning id"
        ).fetchone()[0]
        conn.execute("update sim_state set current_run_id=%s,running=false where id=1", (rid,))
        before = counts(conn)
        asyncio.run(window())
        assert counts(conn) == before
    finally:
        get_settings.cache_clear()


def test_manual_mock_obeys_run_pause_resume_and_never_fakes_url(seeded, conn):
    async def run():
        async with await psycopg.AsyncConnection.connect(dsn(seeded), autocommit=True, row_factory=dict_row) as ac:

            async def source():
                return await (
                    await ac.execute("select * from ingest_sources where code='mock_social_polling'")
                ).fetchone()

            row = await source()
            before = counts(conn)
            with pytest.raises(ValueError, match="активного запуска"):
                await poll_source(ac, row, manual=True)
            assert counts(conn) == before
            rid = conn.execute(
                "insert into sim_runs(kind,label,seed,started_sim,status) select 'free','manual-probe',seed,sim_time,'running' from sim_state where id=1 returning id"
            ).fetchone()[0]
            conn.execute("update sim_state set current_run_id=%s,running=true where id=1", (rid,))
            first = await poll_source(ac, await source(), manual=True)
            assert first["accepted"] == 5 and first["cursor"] == "5"
            rows = conn.execute(
                "select distinct s.run_id,s.received_sim,s.meta->>'synthetic_mode' from signals s join ingest_messages m on m.signal_id=s.id where m.source_code='mock_social_polling'"
            ).fetchall()
            assert rows == [(rid, conn.execute("select sim_time from sim_state where id=1").fetchone()[0], "manual")]
            conn.execute("update sim_state set running=false where id=1")
            conn.execute("update sim_runs set status='paused' where id=%s", (rid,))
            before = counts(conn)
            with pytest.raises(ValueError, match="активного запуска"):
                await poll_source(ac, await source(), manual=True)
            assert counts(conn) == before
            conn.execute("update sim_state set running=true where id=1")
            conn.execute("update sim_runs set status='running' where id=%s", (rid,))
            second = await poll_source(ac, await source(), manual=True)
            assert second["accepted"] == 5 and second["cursor"] == "10"
            before = counts(conn)
            external = {**row, "is_external": True, "config": {"url": "https://example.com/feed"}}
            assert (await poll_source(ac, external, manual=True))["fetched"] == 0
            assert counts(conn) == before

    asyncio.run(run())


@pytest.mark.parametrize("kind", ["free", "live"])
def test_restart_recovers_true_input_but_leaves_legacy_and_history_untouched(seeded, conn, monkeypatch, kind):
    rid = conn.execute(
        "insert into sim_runs(kind,label,seed,started_sim,status) values(%s,'recover-scope',42,%s,'paused') returning id",
        (kind, NOW),
    ).fetchone()[0]
    conn.execute("update sim_state set current_run_id=%s,running=false,sim_time=%s where id=1", (rid, NOW))

    async def ingest(text, origin, contact=None):
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as ac:
            msg = from_api_signal(
                {"channel_code": "chat", "text": text, "external_id": text, "external_contact": contact or {}},
                origin=origin,
            )
            res = await create_signal(ac, msg, source_code="api", run_id=rid, sim_time=NOW, emit_event=False)
            await ac.commit()
            return res["signal_id"]

    real = asyncio.run(ingest("Настоящий незавершённый вход", "jury"))
    old = asyncio.run(ingest("Сообщение mock-ленты #100", "polling", {"nick": "mock_feed"}))
    old_processing = asyncio.run(ingest("Сообщение mock-ленты #101", "polling", {"nick": "mock_feed"}))
    ar = conn.execute(
        "insert into agent_runs(sim_run_id,signal_id,prompt_version,started_at) values(%s,%s,'v1',now()-interval '1 hour') returning id",
        (rid, old_processing),
    ).fetchone()[0]
    conn.execute("update signals set status='processing' where id=%s", (old_processing,))
    historical = conn.execute("select id from signals where origin='sim' order by id limit 1").fetchone()[0]
    conn.execute("update signals set status='new' where id=%s", (historical,))
    monkeypatch.setattr(runner, "expire_hitl", AsyncMock())
    monkeypatch.setattr(runner, "wake_due_followups", AsyncMock())
    service = AgentService(mock_chain(), MOCK_PROFILE, dsn=seeded)
    service.submit = Mock()
    before = counts(conn)
    asyncio.run(service._recover())
    assert [c.args[0] for c in service.submit.call_args_list] == [real]
    assert conn.execute("select outcome from agent_runs where id=%s", (ar,)).fetchone()[0] is None
    assert conn.execute("select status from signals where id=%s", (old_processing,)).fetchone()[0] == "processing"
    assert conn.execute("select status from signals where id=%s", (old,)).fetchone()[0] == "new"
    assert counts(conn) == before


def test_legacy_callbacks_do_not_fire_but_real_followups_still_work(seeded, conn, monkeypatch):
    cid = conn.execute("select id from clients order by id limit 1").fetchone()[0]
    real = make_case(conn, seeded, "callback-real", cid)
    old = make_case(conn, seeded, "callback-old", cid)
    conn.execute(
        "update signals set origin='polling',text='Сообщение mock-ленты #33',external_contact='{\"nick\":\"mock_feed\"}' where id=%s",
        (old["sid"],),
    )
    fids = []
    for case in (real, old):
        ar = conn.execute("select agent_run_id from human_decisions where id=%s", (case["hid"],)).fetchone()[0]
        fid = conn.execute(
            "insert into followups(sim_run_id,agent_run_id,signal_id,incident_id,wake_sim,reason,payload) values(%s,%s,%s,%s,%s,'awaiting_team','{}') returning id",
            (case["rid"], ar, case["sid"], case["iid"], NOW - dt.timedelta(hours=1)),
        ).fetchone()[0]
        fids.append(fid)
    resume = AsyncMock(return_value={})
    monkeypatch.setattr(graph, "resume_after_followup", resume)

    async def run():
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as ac:
            assert await graph.wake_due_followups(ac, sim_time=NOW, chain=mock_chain(), profile=MOCK_PROFILE) == 1
            await ac.commit()

    asyncio.run(run())
    assert resume.call_args.kwargs["followup_id"] == fids[0]
    assert conn.execute("select status from followups where id=%s", (fids[1],)).fetchone()[0] == "scheduled"
    conn.execute(
        "update human_decisions set requested_sim=%s where id=any(%s)",
        (NOW - dt.timedelta(hours=3), [real["hid"], old["hid"]]),
    )
    escalation = AsyncMock()
    monkeypatch.setattr(graph.wt, "escalate_to_manager", escalation)

    async def expire():
        async with await psycopg.AsyncConnection.connect(dsn(seeded)) as ac:
            await graph.expire_hitl(ac, sim_time=NOW, chain=mock_chain(), profile=MOCK_PROFILE)
            await ac.commit()

    asyncio.run(expire())
    assert escalation.call_count == 1
    assert conn.execute("select decision from human_decisions where id=%s", (old["hid"],)).fetchone()[0] is None


async def test_real_http_input_is_processed_in_paused_live_context(seeded, conn, monkeypatch):
    import httpx

    from app.main import create_app

    monkeypatch.setenv("DATABASE_URL", seeded)
    get_settings.cache_clear()
    conn.execute("update sim_state set current_run_id=NULL,running=false where id=1")
    before = conn.execute("select sim_time from sim_state where id=1").fetchone()[0]
    service = AgentService(mock_chain(), MOCK_PROFILE, dsn=seeded)
    app = create_app()
    app.state.agent = service
    body = {
        "channel": "social",
        "external_id": "real-http-idle",
        "client": {},
        "text": "Пожалуйста, расскажите условия дебетовой карты.",
        "timestamp": before.isoformat(),
        "geo": {"source": "none"},
        "origin": "api",
    }
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/ingest/messages", json=body)
            assert response.status_code == 202
            result = response.json()["items"][0]
            assert result["status"] == "accepted"
            await asyncio.gather(*list(service._inflight))
        row = conn.execute(
            "select s.run_id,s.status,a.outcome from signals s join agent_runs a on a.signal_id=s.id where s.id=%s",
            (result["signal_id"],),
        ).fetchone()
        live_id = conn.execute("select current_run_id from sim_state where id=1").fetchone()[0]
        assert conn.execute("select kind from sim_runs where id=%s", (live_id,)).fetchone()[0] == "live"
        assert row and row[0] == live_id and row[2] is not None
        assert conn.execute("select running,sim_time from sim_state where id=1").fetchone() == (False, before)
    finally:
        await service.stop()
        get_settings.cache_clear()


@pytest.mark.parametrize("with_sim", [False, True])
async def test_first_public_requests_share_live_run_without_clock(seeded, conn, monkeypatch, with_sim):
    import httpx

    from app.main import create_app
    from app.sim.engine import Simulator

    monkeypatch.setenv("DATABASE_URL", seeded)
    get_settings.cache_clear()
    conn.execute("update sim_state set current_run_id=NULL,running=false where id=1")
    before = conn.execute("select sim_time,seed,rng_state from sim_state where id=1").fetchone()
    old_live = conn.execute("select count(*) from sim_runs where kind='live'").fetchone()[0]
    app = create_app()
    sim = Simulator(dsn=seeded) if with_sim else None
    if sim:
        await sim.load_state()
        app.state.sim = sim
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            responses = await asyncio.gather(
                *[
                    client.post(
                        "/api/public/reviews",
                        json={
                            "platform": "review_portal",
                            "author_nick": f"live_test_{i}",
                            "text": "Подскажите, пожалуйста, условия обслуживания дебетовой карты.",
                        },
                    )
                    for i in range(3)
                ]
            )
            assert [r.status_code for r in responses] == [202, 202, 202]
        rid = conn.execute("select current_run_id from sim_state where id=1").fetchone()[0]
        assert conn.execute("select count(*) from sim_runs where kind='live'").fetchone()[0] == old_live + 1
        assert conn.execute("select distinct run_id from signals where origin='review_portal'").fetchall() == [(rid,)]
        assert conn.execute("select sim_time,seed,rng_state from sim_state where id=1").fetchone() == before
        assert conn.execute("select running from sim_state where id=1").fetchone() == (False,)
        if sim:
            assert sim.run_id == rid and sim.world is None and sim._task is None and sim.stats["ticks"] == 0
            await sim.shutdown()
            assert conn.execute("select current_run_id,running,sim_time from sim_state where id=1").fetchone() == (
                rid,
                False,
                before[0],
            )
    finally:
        if sim:
            await sim.shutdown()
        get_settings.cache_clear()


async def test_sim_syncs_stale_pointer_without_replacing_existing_context(seeded, conn):
    from app.sim.engine import Simulator

    sim = Simulator(dsn=seeded)
    try:
        await sim.load_state()
        baseline = sim.run_id
        assert await sim.ensure_live_run() == baseline
        conn.execute("update sim_state set current_run_id=NULL where id=1")
        live = await sim.ensure_live_run()
        assert live != baseline and sim.run_id == live
        assert conn.execute("select kind from sim_runs where id=%s", (live,)).fetchone() == ("live",)
        free = conn.execute(
            "insert into sim_runs(kind,label,seed,started_sim,status) select 'free','existing',seed,sim_time,'paused' from sim_state where id=1 returning id"
        ).fetchone()[0]
        conn.execute("update sim_state set current_run_id=%s where id=1", (free,))
        assert await sim.ensure_live_run() == free and sim.run_id == free and sim.run_status == "paused"
        assert sim.clock.running is False and sim.world is None and sim._task is None
    finally:
        await sim.shutdown()


async def test_fixed_seed_world_repeats_after_restore(seeded, conn, tmp_path):
    import subprocess

    from app.sim.baseline import _pg_tool
    from app.sim.engine import Simulator

    archive = tmp_path / "determinism.dump"
    subprocess.run([_pg_tool("pg_dump"), "-Fc", "-f", str(archive), dsn(seeded)], check=True, capture_output=True)

    async def replay():
        sim = Simulator(dsn=seeded)
        try:
            await sim.load_state()
            # Детерминизм сравнивается на рабочем дне, включая тексты; короткий
            # двухчасовой поток при общем RNG может не содержать ни одного сигнала.
            for _ in range(8):
                await sim.step(60)
            await sim.conn.commit()
            events = conn.execute(
                "select event_type,sim_time from sim_events where run_id=%s order by id", (sim.run_id,)
            ).fetchall()
            signals = conn.execute(
                "select channel_code,text,received_sim from signals where run_id=%s order by id", (sim.run_id,)
            ).fetchall()
            return sim.stats.copy(), sim.rng.dump_state(), events, signals
        finally:
            await sim.shutdown()

    first = await replay()
    assert first[0]["ops"] > 0 and first[3]
    subprocess.run(
        [_pg_tool("pg_restore"), "--clean", "--if-exists", "--exit-on-error", "--dbname", dsn(seeded), str(archive)],
        check=True,
        capture_output=True,
    )
    assert await replay() == first
