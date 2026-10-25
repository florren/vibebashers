"""T-077: HITL wait_human, few-shot decide, modify gift, expire_hitl и runner."""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.agent.graph import _load_signal, expire_hitl, load_deps, process_signal
from app.agent.nodes import Deps, _fewshot_for_decide, wait_human
from app.agent.prompts import prompt_version
from app.agent.runner import AgentService
from app.agent.state import new_state
from app.agent.tools.base import ToolContext
from app.config import get_settings
from app.ingest.normalizer import create_signal, from_api_signal
from app.llm.base import LLMProfile
from app.llm.failover import ProviderChain
from app.llm.mock import MockProvider
from app.main import create_app
from app.sim.events import dumps

pytestmark = pytest.mark.integration

PROFILE = LLMProfile(code="mock", provider="mock", model="mock-1", role="main")

FEWSHOT_MATCH = "fewshot_marker_match_tech"
FEWSHOT_OTHER = "fewshot_marker_other_tariff"


def _dsn(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def _chain() -> ProviderChain:
    return ProviderChain([MockProvider()])


def _client(conn: psycopg.Connection, segment: str) -> int:
    row = conn.execute(
        "select id from clients where segment_code = %s and is_active order by id limit 1", (segment,)
    ).fetchone()
    assert row
    return int(row[0])


def _seed_fewshot_pair(conn: psycopg.Connection, run_id: int, sim_time: Any) -> None:
    examples = [
        ("tech_fault", "deposit", "sub_deposits", FEWSHOT_MATCH),
        ("tariff_terms", "debit_card", "processing", FEWSHOT_OTHER),
    ]
    for stype, prod, sys, comment in examples:
        sid = conn.execute(
            "insert into signals (run_id, channel_code, text, received_sim, origin, status, classification) "
            "values (%s, 'chat', %s, %s, 'api', 'closed', %s::jsonb) returning id",
            (
                run_id,
                comment,
                sim_time,
                dumps(
                    {
                        "signal_type": stype,
                        "product": prod,
                        "system": sys,
                        "summary_ru": comment,
                        "criticality": "low",
                        "confidence": 0.9,
                    }
                ),
            ),
        ).fetchone()[0]
        ar = conn.execute(
            "insert into agent_runs (kind, sim_run_id, signal_id, prompt_version, graph_version, thread_id, started_sim) "
            "values ('agent', %s, %s, 'v1', 'v1', %s, %s) returning id",
            (run_id, sid, f"{run_id}:{sid}", sim_time),
        ).fetchone()[0]
        conn.execute(
            "insert into human_decisions (sim_run_id, agent_run_id, signal_id, requested_sim, reason, agent_proposal, "
            "options, recommendation, decision, decided_by, decided_at, use_as_fewshot, comment) "
            "values (%s, %s, %s, %s, 'policy_other', '{}'::jsonb, '[]'::jsonb, '', 'accept', 'test', now(), true, %s)",
            (run_id, ar, sid, sim_time, comment),
        )


async def _ingest_and_run(dsn: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        res = await create_signal(conn, from_api_signal(body), source_code="api", emit_event=False)
        await conn.commit()
        assert res["status"] == "accepted", res
        state = await process_signal(conn, signal_id=int(res["signal_id"]), chain=_chain(), profile=PROFILE)
        assert state is not None
        return int(res["signal_id"]), dict(state)


@pytest.mark.parametrize(
    ("incident_status", "expect_linked"),
    [("in_progress", True), ("closed", False)],
)
def test_wait_human_link_incident_respects_fsm(
    seeded: str, conn: psycopg.Connection, incident_status: str, expect_linked: bool
) -> None:
    run_id = int(conn.execute("select current_run_id from sim_state where id = 1").fetchone()[0])
    sim_time = conn.execute("select sim_time from sim_state where id = 1").fetchone()[0]
    inc = conn.execute("select id from incidents where run_id = %s order by id limit 1", (run_id,)).fetchone()
    if not inc:
        pytest.skip("в сиде нет инцидентов")
    inc_id = int(inc[0])
    conn.execute("update incidents set status = %s where id = %s", (incident_status, inc_id))

    async def _run() -> int | None:
        dsn = _dsn(seeded)
        async with await psycopg.AsyncConnection.connect(dsn) as ac:
            cid = _client(conn, "ultra_vip")
            res = await create_signal(
                ac,
                from_api_signal(
                    {
                        "channel_code": "email",
                        "client_id": cid,
                        "text": "Прошу разобраться с вкладом, ошибка в приложении.",
                    }
                ),
                source_code="api",
                emit_event=False,
            )
            await ac.commit()
            sid = int(res["signal_id"])
            sig = await _load_signal(ac, sid)
            assert sig
            ar = await (
                await ac.execute(
                    "insert into agent_runs (kind, sim_run_id, signal_id, client_id, prompt_version, graph_version, "
                    "thread_id, started_sim) values ('agent', %s, %s, %s, %s, 'v1', %s, %s) returning id",
                    (run_id, sid, cid, prompt_version(), f"{run_id}:{sid}", sim_time),
                )
            ).fetchone()
            agent_run_id = int(ar[0])  # type: ignore[index]
            state = new_state(run_id, sig, agent_run_id, prompt_version())
            state["decision"] = {
                "incident_action": "link_existing",
                "link_incident_id": inc_id,
                "human_reason": "ultra_vip",
                "human_options": [{"code": "accept", "label_ru": "Принять"}],
                "human_recommendation": "Проверить связь с инцидентом",
            }
            deps = await load_deps(
                ac, chain=_chain(), profile=PROFILE, run_id=run_id, agent_run_id=agent_run_id, sim_time=sim_time
            )
            await wait_human(state, deps)
            await ac.commit()
            row = await (
                await ac.execute("select incident_id from human_decisions where signal_id = %s", (sid,))
            ).fetchone()
            return int(row[0]) if row and row[0] is not None else None

    linked = asyncio.run(_run())
    if expect_linked:
        assert linked == inc_id
        assert conn.execute("select status from incidents where id = %s", (inc_id,)).fetchone()[0] == "awaiting_human"
    else:
        assert linked is None
        assert conn.execute("select status from incidents where id = %s", (inc_id,)).fetchone()[0] == incident_status


def test_load_deps_fewshot_includes_classification(seeded: str, conn: psycopg.Connection) -> None:
    run_id = int(conn.execute("select current_run_id from sim_state where id = 1").fetchone()[0])
    sim_time = conn.execute("select sim_time from sim_state where id = 1").fetchone()[0]
    sig_row = conn.execute(
        "insert into signals (run_id, channel_code, text, received_sim, origin, status, classification) "
        "values (%s, 'chat', 'тест few-shot', %s, 'api', 'closed', %s::jsonb) returning id",
        (
            run_id,
            sim_time,
            dumps(
                {
                    "signal_type": "tech_fault",
                    "product": "deposit",
                    "system": "sub_deposits",
                    "summary_ru": "тест",
                    "criticality": "medium",
                    "confidence": 0.9,
                }
            ),
        ),
    ).fetchone()
    assert sig_row
    sid = int(sig_row[0])
    ar = conn.execute(
        "insert into agent_runs (kind, sim_run_id, signal_id, prompt_version, graph_version, thread_id, started_sim) "
        "values ('agent', %s, %s, 'v1', 'v1', %s, %s) returning id",
        (run_id, sid, f"{run_id}:{sid}", sim_time),
    ).fetchone()
    conn.execute(
        "insert into human_decisions (sim_run_id, agent_run_id, signal_id, requested_sim, reason, agent_proposal, "
        "options, recommendation, decision, decided_by, decided_at, use_as_fewshot) "
        "values (%s, %s, %s, %s, 'policy_other', '{}'::jsonb, '[]'::jsonb, '', 'accept', 'test', now(), true)",
        (run_id, int(ar[0]), sid, sim_time),
    )

    async def _load() -> list[dict[str, Any]]:
        async with await psycopg.AsyncConnection.connect(_dsn(seeded)) as ac:
            deps = await load_deps(
                ac, chain=_chain(), profile=PROFILE, run_id=run_id, agent_run_id=int(ar[0]), sim_time=sim_time
            )
            return deps.fewshot

    few = asyncio.run(_load())
    assert few and few[0].get("signal_type") == "tech_fault"
    assert few[0].get("product") == "deposit"
    assert few[0].get("system") == "sub_deposits"


def test_decide_fewshot_filters_by_classification(seeded: str, conn: psycopg.Connection) -> None:
    run_id = int(conn.execute("select current_run_id from sim_state where id = 1").fetchone()[0])
    sim_time = conn.execute("select sim_time from sim_state where id = 1").fetchone()[0]
    _seed_fewshot_pair(conn, run_id, sim_time)

    async def _load() -> list[dict[str, Any]]:
        async with await psycopg.AsyncConnection.connect(_dsn(seeded)) as ac:
            deps = await load_deps(
                ac, chain=_chain(), profile=PROFILE, run_id=run_id, agent_run_id=1, sim_time=sim_time
            )
            return deps.fewshot

    few = asyncio.run(_load())
    deps_stub = Deps(
        ctx=ToolContext(object(), run_id=run_id, agent_run_id=1, sim_time=sim_time),  # type: ignore[arg-type]
        chain=_chain(),
        profile=PROFILE,
        fewshot=few,
    )
    picked = _fewshot_for_decide(
        deps_stub, {"signal_type": "tech_fault", "product": "deposit", "system": "sub_deposits"}
    )
    assert isinstance(picked, list)
    assert all(x.get("signal_type") == "tech_fault" for x in picked)
    assert any(x.get("comment") == FEWSHOT_MATCH for x in picked)
    fallback = _fewshot_for_decide(deps_stub, {"signal_type": "legal_regulatory"})
    assert isinstance(fallback, list) and len(fallback) == len(few[:5])


def test_decide_prompt_records_fewshot(seeded: str, conn: psycopg.Connection) -> None:
    run_id = int(conn.execute("select current_run_id from sim_state where id = 1").fetchone()[0])
    sim_time = conn.execute("select sim_time from sim_state where id = 1").fetchone()[0]
    _seed_fewshot_pair(conn, run_id, sim_time)
    cid = _client(conn, "ultra_vip")
    signal_id, state = asyncio.run(
        _ingest_and_run(
            _dsn(seeded),
            {
                "channel_code": "email",
                "client_id": cid,
                "text": "При открытии вклада система выдаёт ошибку, депозит не создаётся — сбой на стороне банка.",
            },
        )
    )
    assert state["outcome"] == "awaiting_human"
    prompt = conn.execute(
        "select prompt from agent_steps where run_id = (select id from agent_runs where signal_id = %s) "
        "and node = 'decide' order by seq desc limit 1",
        (signal_id,),
    ).fetchone()
    assert prompt and prompt[0]
    body = prompt[0]
    assert "Примеры решений людей" in body
    assert FEWSHOT_MATCH in body
    assert FEWSHOT_OTHER not in body


def test_hitl_modify_gift_via_api(seeded: str, conn: psycopg.Connection) -> None:
    os.environ["DATABASE_URL"] = seeded
    os.environ["APP_ENV"] = "test"
    get_settings.cache_clear()
    cid = _client(conn, "vip")
    signal_id, _state = asyncio.run(
        _ingest_and_run(
            _dsn(seeded),
            {
                "channel_code": "email",
                "client_id": cid,
                "text": "Уже третий раз ошибка при оплате картой, очень недоволен сервисом банка.",
            },
        )
    )
    hd = conn.execute("select id, options from human_decisions where signal_id = %s", (signal_id,)).fetchone()
    assert hd and len(hd[1]) == 3
    gift_code = "lounge_pass"
    points = 1000
    try:
        with TestClient(create_app()) as client:
            r = client.post(
                f"/api/hitl/{hd[0]}",
                json={
                    "decision": "modify",
                    "modified_proposal": {
                        "gift": {"gift_code": gift_code, "points": points},
                        "client_action": {"text_ru": "Мы уже разбираемся с вашим обращением."},
                    },
                    "comment": "увеличить подарок",
                    "use_as_fewshot": True,
                },
            )
            assert r.status_code == 200, r.text
        notif = conn.execute(
            "select body from notifications where signal_id = %s and recipient_type = 'client' order by id desc limit 1",
            (signal_id,),
        ).fetchone()
        assert notif and notif[0]
        body = notif[0] if isinstance(notif[0], str) else str(notif[0])
        assert str(points) in body and gift_code in body
        task = conn.execute(
            "select payload from tasks where incident_id = (select incident_id from agent_runs where signal_id = %s) "
            "and kind = 'gift' limit 1",
            (signal_id,),
        ).fetchone()
        assert task and task[0]
        payload = task[0] if isinstance(task[0], dict) else json.loads(task[0])
        assert payload.get("gift", {}).get("gift_code") == gift_code
        assert payload.get("gift", {}).get("points") == points
    finally:
        get_settings.cache_clear()


def test_expire_hitl_escalates_pending(seeded: str, conn: psycopg.Connection) -> None:
    cid = _client(conn, "ultra_vip")
    signal_id, _ = asyncio.run(
        _ingest_and_run(
            _dsn(seeded),
            {"channel_code": "email", "client_id": cid, "text": "VIP: ошибка при переводе, нужна помощь."},
        )
    )
    hd = conn.execute("select id, agent_run_id from human_decisions where signal_id = %s", (signal_id,)).fetchone()
    assert hd
    sim_time = conn.execute("select sim_time from sim_state where id = 1").fetchone()[0]
    conn.execute(
        "update human_decisions set requested_sim = %s - interval '3 hours' where id = %s",
        (sim_time, hd[0]),
    )

    async def _expire() -> None:
        async with await psycopg.AsyncConnection.connect(_dsn(seeded)) as ac:
            await expire_hitl(ac, sim_time=sim_time, chain=_chain(), profile=PROFILE)

    asyncio.run(_expire())
    assert conn.execute("select decision from human_decisions where id = %s", (hd[0],)).fetchone()[0] is None
    esc = conn.execute("select count(*) from escalations where agent_run_id = %s", (hd[1],)).fetchone()[0]
    assert esc == 1


def test_expire_hitl_timeout_without_team_cx(seeded: str, conn: psycopg.Connection) -> None:
    cid = _client(conn, "ultra_vip")
    signal_id, _ = asyncio.run(
        _ingest_and_run(
            _dsn(seeded),
            {"channel_code": "chat", "client_id": cid, "text": "Снова не работает перевод, жду решения."},
        )
    )
    hd = conn.execute("select id, agent_run_id from human_decisions where signal_id = %s", (signal_id,)).fetchone()
    assert hd
    sim_time = conn.execute("select sim_time from sim_state where id = 1").fetchone()[0]
    conn.execute(
        "update human_decisions set requested_sim = %s - interval '4 hours' where id = %s",
        (sim_time, hd[0]),
    )
    conn.execute(
        "update settings set value = jsonb_set(coalesce(value, '{}'::jsonb), '{hitl_timeout_escalate}', 'false'::jsonb) "
        "where key = 'policies'"
    )
    try:

        async def _expire() -> None:
            async with await psycopg.AsyncConnection.connect(_dsn(seeded)) as ac:
                await expire_hitl(ac, sim_time=sim_time, chain=_chain(), profile=PROFILE)

        asyncio.run(_expire())
        row = conn.execute("select decision, decided_by from human_decisions where id = %s", (hd[0],)).fetchone()
        assert row[0] == "modify" and row[1] == "timeout"
        run = conn.execute("select outcome, incident_id from agent_runs where id = %s", (hd[1],)).fetchone()
        assert run[0] == "completed" and run[1] is not None
        notif = conn.execute(
            "select template_code from notifications where signal_id = %s and recipient_type = 'client' order by id desc limit 1",
            (signal_id,),
        ).fetchone()
        assert notif and notif[0] == "ack_received"
        gifts = conn.execute(
            "select count(*) from tasks where incident_id = %s and kind = 'gift'", (run[1],)
        ).fetchone()[0]
        assert gifts == 0
    finally:
        conn.execute(
            "update settings set value = coalesce(value, '{}'::jsonb) - 'hitl_timeout_escalate' where key = 'policies'"
        )


def test_agent_recover_runs_expire_hitl(seeded: str, conn: psycopg.Connection) -> None:
    cid = _client(conn, "ultra_vip")
    signal_id, _ = asyncio.run(
        _ingest_and_run(
            _dsn(seeded),
            {"channel_code": "chat", "client_id": cid, "text": "Ultra VIP: снова ошибка в приложении."},
        )
    )
    hd = conn.execute("select id, agent_run_id from human_decisions where signal_id = %s", (signal_id,)).fetchone()
    assert hd
    sim_time = conn.execute("select sim_time from sim_state where id = 1").fetchone()[0]
    conn.execute(
        "update human_decisions set requested_sim = %s - interval '5 hours' where id = %s",
        (sim_time, hd[0]),
    )
    before = conn.execute("select count(*) from escalations where agent_run_id = %s", (hd[1],)).fetchone()[0]

    async def _recover() -> None:
        svc = AgentService(_chain(), PROFILE, dsn=_dsn(seeded), concurrency=1)
        await svc._recover()

    asyncio.run(_recover())
    assert conn.execute("select decision from human_decisions where id = %s", (hd[0],)).fetchone()[0] is None
    assert conn.execute("select outcome from agent_runs where id = %s", (hd[1],)).fetchone()[0] == "awaiting_human"
    after = conn.execute("select count(*) from escalations where agent_run_id = %s", (hd[1],)).fetchone()[0]
    assert after == before + 1
