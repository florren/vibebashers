"""T-067: PostgreSQL READ ONLY и фактическая неизменность доменных таблиц."""

import asyncio
import json

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql

from app.agent.comparison import mock_comparison
from app.agent.runner import AgentService
from app.api.metrics import get_metrics_dashboard
from app.config import get_settings
from app.ingest.normalizer import create_signal, from_api_signal
from app.llm.mock import MockProvider
from app.main import create_app
from tests.helpers import MOCK_PROFILE, dsn, mock_chain, new_run, sim_now

pytestmark = pytest.mark.integration
DOMAIN_TABLES = (
    "signals",
    "incidents",
    "incident_signals",
    "notifications",
    "tasks",
    "human_decisions",
    "ledger_entries",
    "followups",
    "clients",
    "client_states",
    "client_reactions",
    "rule_evaluations",
    "escalations",
    "external_posts",
    "external_replies",
    "incident_economics",
    "team_actions",
    "incident_status_history",
    "incident_artifacts",
    "churn_events",
)


async def fingerprints(conn):
    result = {}
    for table in DOMAIN_TABLES:
        query = sql.SQL(
            "select md5(coalesce(string_agg(to_jsonb(t)::text,'' order by to_jsonb(t)::text),'')) from {} t"
        ).format(sql.Identifier(table))
        result[table] = (await (await conn.execute(query)).fetchone())[0]
    return result


@pytest.fixture
def configured(seeded, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", seeded)
    get_settings.cache_clear()
    yield seeded
    get_settings.cache_clear()


async def accepted(conn):
    rid = await new_run(conn, "T067 comparison")
    result = await create_signal(
        conn,
        from_api_signal(
            {"channel_code": "chat", "text": "Ошибка 500 при открытии вклада", "client_id": 1}, origin="jury"
        ),
        source_code="api",
        run_id=rid,
        sim_time=await sim_now(conn),
        emit_event=False,
    )
    await conn.commit()
    return int(result["signal_id"])


async def test_saved_comparison_preserves_every_domain_table(configured):
    async with await psycopg.AsyncConnection.connect(dsn(configured), autocommit=True) as conn:
        sid = await accepted(conn)
        before = await fingerprints(conn)
        rid = (await (await conn.execute("select run_id from signals where id=%s", (sid,))).fetchone())[0]
        metrics_before = json.loads((await get_metrics_dashboard(window="run", run_id=str(rid))).body)
        async with mock_comparison(sid) as comparison:
            setting = await (await comparison.deps.ctx.conn.execute("show transaction_read_only")).fetchone()
            assert setting == ("on",)
            compare_id = await comparison.run()
        assert await fingerprints(conn) == before
        metrics_after = json.loads((await get_metrics_dashboard(window="run", run_id=str(rid))).body)
        for key in ("agent_runs", "autonomous_share", "hitl_share", "tokens_total", "agent_latency_p50_ms"):
            assert metrics_after[key] == metrics_before[key]
        row = await (
            await conn.execute(
                "select kind,outcome,signal_id,incident_id,needed_human from agent_runs where id=%s", (compare_id,)
            )
        ).fetchone()
        assert row == ("compare", "completed", sid, None, False)
        steps = await (
            await conn.execute("select node,status,output from agent_steps where run_id=%s order by seq", (compare_id,))
        ).fetchall()
        assert [s[0] for s in steps] == ["normalize", "identify_client", "gather_context", "classify", "decide", "act"]
        assert steps[-1][1] == "skipped" and steps[-1][2]["dry_run"] is True


async def test_comparison_uses_snapshot_before_primary_changes(configured):
    async with await psycopg.AsyncConnection.connect(dsn(configured), autocommit=True) as conn:
        sid = await accepted(conn)
        async with mock_comparison(sid) as comparison:
            await conn.execute("update signals set text='Спасибо, всё работает' where id=%s", (sid,))
            old = await (
                await comparison.deps.ctx.conn.execute("select text from signals where id=%s", (sid,))
            ).fetchone()
            assert old == ("Ошибка 500 при открытии вклада",)
            await comparison.run()
        assert (await (await conn.execute("select text from signals where id=%s", (sid,))).fetchone())[
            0
        ] == "Спасибо, всё работает"


def test_jury_returns_separate_runs_and_can_disable_compare(configured, monkeypatch):
    original = MockProvider.complete_structured
    entered = asyncio.Event()

    async def barrier(self, messages, schema, profile, **kwargs):
        if profile.code == "compare_mock":
            await asyncio.wait_for(entered.wait(), 2)
        else:
            entered.set()
        return await original(self, messages, schema, profile, **kwargs)

    monkeypatch.setattr(MockProvider, "complete_structured", barrier)
    with TestClient(create_app()) as client:
        client.app.state.agent = AgentService(mock_chain(), MOCK_PROFILE, dsn=configured)
        response = client.post(
            "/api/signals", json={"text": "Ошибка 500 при открытии вклада", "channel_code": "chat", "client_id": 1}
        )
        assert response.status_code == 202, response.text
        data = response.json()
        assert data["agent_run_id"] and data["compare_run_id"] and data["agent_run_id"] != data["compare_run_id"]
        assert entered.is_set()
        with psycopg.connect(dsn(configured)) as conn:
            rows = conn.execute(
                "select id,kind,outcome from agent_runs where signal_id=%s order by id", (data["signal_id"],)
            ).fetchall()
            assert len(rows) == 2 and {row[1] for row in rows} == {"agent", "compare"}
            assert next(row for row in rows if row[1] == "compare")[2] == "completed"
        response = client.post(
            "/api/signals", json={"text": "Какая ставка по вкладу?", "channel_code": "chat", "compare_with_mock": False}
        )
        assert response.status_code == 202, response.text
        assert response.json()["compare_run_id"] is None


def test_standalone_compare_persists_both_results_without_signal(configured):
    with psycopg.connect(dsn(configured)) as conn:
        before = conn.execute("select count(*) from signals").fetchone()[0]
    with TestClient(create_app()) as client:
        response = client.post(
            "/api/agent/compare", json={"text": "Верните комиссию 400 рублей", "channel_code": "chat"}
        )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["llm_run_id"] != data["mock_run_id"]
    with psycopg.connect(dsn(configured)) as conn:
        assert conn.execute("select count(*) from signals").fetchone()[0] == before
        rows = conn.execute(
            "select kind,outcome,signal_id from agent_runs where id=any(%s)",
            ([data["llm_run_id"], data["mock_run_id"]],),
        ).fetchall()
        assert rows == [("compare", "completed", None), ("compare", "completed", None)]


@pytest.mark.parametrize("mode", ["mock", "replay", "fallback"])
def test_standalone_trace_records_actual_provider_and_model(configured, mode):
    """Настоящие Mock/Replay adapters; cassette transport только test-only, без live calls."""
    from app.contracts.registry import deref
    from app.llm.base import LLMProfile, ProviderError
    from app.llm.failover import ProviderChain
    from app.replay.provider import ReplayProvider

    text = "Верните комиссию за перевод"
    obj, _, _ = asyncio.run(
        MockProvider().complete_structured([], deref("agent/classification"), MOCK_PROFILE, timeout_s=1)
    )

    class TestCassetteTransport:
        def get(self, *args):
            return {
                "response": obj,
                "model": "recorded-test-model",
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            }

    class UnavailableTransport:
        name = "gigachat"

        async def complete_structured(self, *args, **kwargs):
            raise ProviderError("unavailable", "test-only unavailable transport")

    profile = LLMProfile(code="requested", provider="gigachat", model="requested-test-model")
    if mode == "mock":
        chain, profile = mock_chain(), MOCK_PROFILE
    elif mode == "replay":
        chain = ProviderChain([ReplayProvider(TestCassetteTransport())])
    else:
        chain = ProviderChain([UnavailableTransport(), MockProvider()])
    with psycopg.connect(dsn(configured)) as conn:
        before = conn.execute("select count(*) from signals").fetchone()[0]
    with TestClient(create_app()) as client:
        client.app.state.llm_chain, client.app.state.llm_profile = chain, profile
        response = client.post("/api/agent/compare", json={"text": text, "channel_code": "chat"})
        assert response.status_code == 200
        data = response.json()
        main_trace = client.get(f"/api/agent/runs/{data['llm_run_id']}")
        mock_trace = client.get(f"/api/agent/runs/{data['mock_run_id']}")
        assert main_trace.status_code == mock_trace.status_code == 200
    step = main_trace.json()["steps"][0]
    assert step["model"] == ("replay:recorded-test-model" if mode == "replay" else "mock:mock-rules-v1")
    assert step["status"] == ("fallback" if mode == "fallback" else "ok")
    assert mock_trace.json()["steps"][0]["model"] == "mock:mock-rules-v1"
    with psycopg.connect(dsn(configured)) as conn:
        assert conn.execute("select count(*) from signals").fetchone()[0] == before
