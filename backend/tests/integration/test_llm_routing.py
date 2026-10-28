"""Маршрутизация графа и живого контура двойника на синтетических провайдерах."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import psycopg
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from app.agent.graph import process_signal
from app.config import Settings, get_settings
from app.ingest.normalizer import create_signal, from_api_signal
from app.llm.failover import ProviderChain
from app.llm.mock import MockProvider
from app.llm.roles import select
from app.main import create_app
from app.sim.twins import TwinService


class RecordingProvider(MockProvider):
    name = "gigachat"

    def __init__(self):
        super().__init__()
        self.models = []

    async def complete_structured(self, messages, schema, profile, *, timeout_s):
        self.models.append(profile.model)
        obj, usage, raw = await super().complete_structured(messages, schema, profile, timeout_s=timeout_s)
        usage.model = profile.model
        if profile.role == "twin":
            obj = {
                "reaction": "asks_again",
                "tone": "neutral",
                "satisfaction": 0.4,
                "churn_intent": False,
                "text_ru": "Уточните, пожалуйста, что мне делать дальше?",
            }
        return obj, usage, raw


def test_graph_main_fast_and_twin_reaction_idempotency(seeded, conn):
    dsn = seeded.replace("postgresql+psycopg://", "postgresql://", 1)
    provider = RecordingProvider()
    chain = ProviderChain([provider], append_mock=False)
    cid = conn.execute(
        "select o.client_id from operations o join clients c on c.id=o.client_id where o.error_code='PROC-QR-FEE-CHARGED' and c.segment_code<>'ultra_vip' order by o.started_sim desc limit 1"
    ).fetchone()[0]

    async def run():
        async with await psycopg.AsyncConnection.connect(dsn) as c:
            async with c.cursor(row_factory=dict_row) as cur:
                await cur.execute("select * from llm_profiles order by id")
                profiles = await cur.fetchall()
            chain.role_profiles = select(Settings(_env_file=None, llm_provider="gigachat"), profiles, {})
            ingested = await create_signal(
                c,
                from_api_signal(
                    {
                        "channel_code": "chat",
                        "client_id": cid,
                        "text": "Оплатил по QR 3200 рублей, списали комиссию. Верните комиссию.",
                    }
                ),
                source_code="api",
                emit_event=False,
            )
            await c.commit()
            sid = ingested["signal_id"]
            state = await process_signal(c, signal_id=sid, chain=chain, profile=chain.role_profiles["main"])
            assert state["outcome"] == "completed", state["errors"]
            assert provider.models[0] == "GigaChat-3-Lightning"
            assert all(m == "GigaChat-3-Ultra" for m in provider.models[1:])
            nid = (
                await (
                    await c.execute(
                        "select id from notifications where signal_id=%s and recipient_type='client' and status='sent' order by id desc limit 1",
                        (sid,),
                    )
                ).fetchone()
            )[0]
            # Отдельный синтетический бюджет: проверяем маршрут, а не длину mock-промптов.
            await c.execute("update agent_runs set total_tokens=1000000 where signal_id=%s and kind='agent'", (sid,))
            await c.commit()
        async with await psycopg.AsyncConnection.connect(dsn, autocommit=True, row_factory=dict_row) as c:
            service = TwinService(chain, chain.role_profiles["main"])
            aid = await service.react(c, nid)
            assert aid is not None
            assert provider.models[-1] == "GigaChat-3-Pro"
            before = len(provider.models)
            assert await service.react(c, nid) is None
            assert len(provider.models) == before
            reaction = await (
                await c.execute("select * from client_reactions where agent_run_id=%s", (aid,))
            ).fetchone()
            assert reaction["notification_id"] == nid and reaction["reaction"] == "asks_again"
            child = await (
                await c.execute(
                    "select id,origin,parent_signal_id from signals where parent_signal_id=%s order by id desc limit 1",
                    (sid,),
                )
            ).fetchone()
            assert child["origin"] == "twin" and child["parent_signal_id"] == sid
            trace = await (
                await c.execute("select kind,llm_profile_id,total_tokens from agent_runs where id=%s", (aid,))
            ).fetchone()
            assert trace["kind"] == "client_twin" and trace["total_tokens"] > 0 and trace["llm_profile_id"] is not None
            step = await (await c.execute("select model,output from agent_steps where run_id=%s", (aid,))).fetchone()
            assert step["model"] == "GigaChat-3-Pro" and step["output"]["llm_source"] == "mock"
            # Ни лимит, ни отключение двойников не вызывают модель.
            await c.execute(
                "insert into settings(key,value) values('twins','{\"daily_limit\":0}') on conflict(key) do update set value=excluded.value"
            )
            other = (
                await (
                    await c.execute(
                        "insert into notifications(run_id,recipient_type,client_id,signal_id,channel_code,body,status,sent_sim) select run_id,recipient_type,client_id,signal_id,channel_code,body,status,sent_sim from notifications where id=%s returning id",
                        (nid,),
                    )
                ).fetchone()
            )["id"]
            assert await service.react(c, other) is None
            assert len(provider.models) == before

    asyncio.run(run())


def test_setup_hot_switches_roles_and_rejects_invalid_without_partial_save(seeded, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", seeded)
    monkeypatch.setenv("LLM_PROVIDER", "gigachat")
    get_settings.cache_clear()
    app = create_app()
    try:
        with TestClient(app) as client:
            rows = client.get("/api/settings/llm-profiles").json()
            ids = {r["code"]: r["id"] for r in rows}
            body = {
                "llm": {
                    "main_profile_id": ids["gigachat_ultra"],
                    "fast_profile_id": ids["gigachat_lightning"],
                    "twin_profile_id": ids["gigachat_pro"],
                }
            }
            spy = SimpleNamespace(chain=app.state.llm_chain, profile=app.state.llm_profile, stop=AsyncMock())
            app.state.agent = spy
            assert client.put("/api/setup", json=body).status_code == 200
            assert app.state.llm_profile.model == "GigaChat-3-Ultra"
            assert spy.profile.model == "GigaChat-3-Ultra"
            assert app.state.llm_fast_profile.model == "GigaChat-3-Lightning"
            assert app.state.llm_twin_profile.model == "GigaChat-3-Pro"
            before = client.get("/api/setup").json()["llm"]
            invalid = {"llm": {**body["llm"], "fast_profile_id": ids["gigachat_ultra"]}}
            assert client.put("/api/setup", json=invalid).status_code == 422
            assert client.get("/api/setup").json()["llm"] == before
            invalid = {"llm": {**body["llm"], "main_profile_id": 999999}}
            assert client.put("/api/setup", json=invalid).status_code == 422
            assert client.get("/api/setup").json()["llm"] == before
            main = next(p for p in rows if p["id"] == ids["gigachat_ultra"])
            assert (
                client.patch(
                    "/api/settings/llm-profiles/" + str(main["id"]), json={**main, "model": "GigaChat-3-Pro"}
                ).status_code
                == 200
            )
            assert app.state.llm_profile.model == "GigaChat-3-Pro"
            assert spy.profile.model == "GigaChat-3-Pro"
            assert (
                client.patch(
                    "/api/settings/llm-profiles/" + str(main["id"]), json={**main, "is_active": False}
                ).status_code
                == 422
            )
    finally:
        get_settings.cache_clear()


def test_twin_worker_waits_for_completed_agent_and_skips_old_notifications(seeded, monkeypatch):
    import time

    monkeypatch.setenv("DATABASE_URL", seeded)
    get_settings.cache_clear()
    dsn = seeded.replace("postgresql+psycopg://", "postgresql://", 1)
    provider = RecordingProvider()
    chain = ProviderChain([provider], append_mock=False)

    async def check():
        async with await psycopg.AsyncConnection.connect(dsn, autocommit=True, row_factory=dict_row) as c:
            st = await (await c.execute("select current_run_id,sim_time from sim_state where id=1")).fetchone()
            cid = (await (await c.execute("select id from clients where is_active order by id limit 1")).fetchone())[
                "id"
            ]
            rows = await (await c.execute("select * from llm_profiles order by id")).fetchall()
            chain.role_profiles = select(Settings(_env_file=None, llm_provider="gigachat"), rows, {})
            service = TwinService(chain, chain.role_profiles["main"])
            service.start()
            try:
                await asyncio.sleep(0.1)
                assert provider.models == []
                msg = from_api_signal(
                    {
                        "client_id": cid,
                        "channel_code": "chat",
                        "text": "Синтетическое обращение для проверки очереди двойника.",
                    }
                )
                sid = (
                    await create_signal(
                        c,
                        msg,
                        source_code="api",
                        run_id=st["current_run_id"],
                        sim_time=st["sim_time"],
                        emit_event=False,
                    )
                )["signal_id"]
                aid = (
                    await (
                        await c.execute(
                            "insert into agent_runs(kind,sim_run_id,signal_id,client_id,prompt_version,started_sim,total_tokens) values('agent',%s,%s,%s,'test',%s,1000000) returning id",
                            (st["current_run_id"], sid, cid, st["sim_time"]),
                        )
                    ).fetchone()
                )["id"]
                nid = (
                    await (
                        await c.execute(
                            "insert into notifications(run_id,recipient_type,client_id,signal_id,channel_code,body,status,sent_sim) values(%s,'client',%s,%s,'chat','Мы получили обращение.','sent',%s) returning id",
                            (st["current_run_id"], cid, sid, st["sim_time"]),
                        )
                    ).fetchone()
                )["id"]
                await asyncio.sleep(1.1)
                assert provider.models == []
                await c.execute("update agent_runs set finished_at=now(),outcome='completed' where id=%s", (aid,))
                deadline = time.monotonic() + 4
                while time.monotonic() < deadline:
                    reaction = await (
                        await c.execute("select id from client_reactions where notification_id=%s", (nid,))
                    ).fetchone()
                    if reaction:
                        break
                    await asyncio.sleep(0.05)
                assert reaction is not None
                assert provider.models == ["GigaChat-3-Pro"]
                # Отказ схемы фиксируется отдельно и не запускает бесконечные повторы.
                provider.complete_structured = AsyncMock(return_value=({}, SimpleNamespace(), ""))
                other = (
                    await (
                        await c.execute(
                            "insert into notifications(run_id,recipient_type,client_id,signal_id,channel_code,body,status,sent_sim) select run_id,recipient_type,client_id,signal_id,channel_code,body,status,sent_sim from notifications where id=%s returning id",
                            (nid,),
                        )
                    ).fetchone()
                )["id"]
                failed = await service.react(c, other)
                status = await (
                    await c.execute("select outcome,error from agent_runs where id=%s", (failed,))
                ).fetchone()
                assert status["outcome"] == "failed" and "bad_output" in status["error"]
                assert await service.react(c, other) is None
            finally:
                await service.stop()
                assert service._task is None

    try:
        asyncio.run(check())
    finally:
        get_settings.cache_clear()
