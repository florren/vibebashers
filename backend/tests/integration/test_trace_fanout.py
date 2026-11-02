"""T-234: настоящее read-only раскрытие всего веера без LLM/внешних каналов."""

import asyncio
import json
import math
import time
import tracemalloc
from pathlib import Path
from unittest.mock import AsyncMock

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql

from app.config import get_settings
from app.contracts.events.trace.trace_relation_page import TraceRelationPage
from app.ingest.normalizer import create_signal, from_api_signal
from app.main import create_app
from tests.helpers import dsn, new_run, sim_now

pytestmark = pytest.mark.integration
PRIVATE = "+7 900 000-00-12 @demo_private ui_test@example.com"


@pytest.fixture
def configured(seeded, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", seeded)
    get_settings.cache_clear()
    bomb = AsyncMock(side_effect=AssertionError("read-only fan API must never call LLM"))
    monkeypatch.setattr("app.llm.failover.ProviderChain.complete_structured", bomb)
    yield seeded
    assert bomb.call_count == 0
    get_settings.cache_clear()


def make_case(url, n=12):
    async def setup():
        async with await psycopg.AsyncConnection.connect(dsn(url)) as conn:
            own = await new_run(conn, "T234 fan fixture", kind="free")
            foreign = await new_run(conn, "T234 foreign fixture", kind="free")
            now = await sim_now(conn)
            base_signal, base_run, cid = await (
                await conn.execute(
                    "select s.id,s.run_id,s.client_id from signals s join sim_runs r on r.id=s.run_id where r.kind='baseline' and s.client_id is not null order by s.id limit 1"
                )
            ).fetchone()
            incident = (
                await (
                    await conn.execute(
                        "insert into incidents(run_id,title,incident_type,team_code,complexity,criticality,priority,created_by,created_sim,sla_due_sim,take_due_sim) values(%s,'T234 fixture','tech_fault','team_cx','easy','medium',2,'scenario',%s,%s+interval '1 day',%s+interval '1 hour') returning id",
                        (own, now, now, now),
                    )
                ).fetchone()
            )[0]
            ids = []
            for i in range(n):
                msg = from_api_signal(
                    {
                        "channel_code": "chat",
                        "client_id": cid,
                        "text": f"Ошибка проверки T234 номер {i}",
                        "external_id": f"t234-{own}-{i}",
                    }
                )
                result = await create_signal(conn, msg, source_code="api", run_id=own, sim_time=now, emit_event=False)
                assert result["status"] == "accepted"
                ids.append(int(result["signal_id"]))
            other = await create_signal(
                conn,
                from_api_signal(
                    {
                        "channel_code": "chat",
                        "client_id": cid,
                        "text": "Чужой запуск T234",
                        "external_id": f"t234-foreign-{foreign}",
                    }
                ),
                source_code="api",
                run_id=foreign,
                sim_time=now,
                emit_event=False,
            )
            async with conn.cursor() as cur:
                await cur.executemany(
                    "insert into incident_signals(incident_id,signal_id,linked_sim) values(%s,%s,%s)",
                    [(incident, sid, now) for sid in [*ids, base_signal, other["signal_id"]]],
                )
                await cur.executemany(
                    "insert into notifications(run_id,recipient_type,client_id,incident_id,channel_code,body,status) values(%s,'client',%s,%s,'chat',%s,'queued')",
                    [
                        (rid, cid, incident, f"T234 queued fixture {i}: {PRIVATE}")
                        for i, rid in enumerate([own] * n + [base_run, foreign])
                    ],
                )
            notices = await (
                await conn.execute("select id,run_id from notifications where incident_id=%s order by id", (incident,))
            ).fetchall()
            await conn.execute("update sim_state set current_run_id=%s where id=1", (own,))
            await conn.commit()
            return {
                "own": own,
                "foreign": foreign,
                "baseline": base_run,
                "client": cid,
                "incident": incident,
                "signals": set(ids) | {base_signal},
                "foreign_signal": other["signal_id"],
                "notices": {rid for rid, run in notices if run != foreign},
                "all_notices": {rid for rid, _ in notices},
            }

    return asyncio.run(setup())


def fingerprints(url):
    with psycopg.connect(dsn(url)) as conn:
        conn.execute("set transaction isolation level repeatable read, read only")
        tables = conn.execute("select tablename from pg_tables where schemaname='public' order by tablename").fetchall()
        return {
            name: conn.execute(
                sql.SQL(
                    "select count(*),md5(coalesce(string_agg(to_jsonb(t)::text,'' order by to_jsonb(t)::text),'')) from {} t"
                ).format(sql.Identifier(name))
            ).fetchone()
            for (name,) in tables
        }


def walk(client, path, **query):
    cursor, ids, seen_cursors = None, [], set()
    while True:
        response = client.get(path, params={**query, **({"cursor": cursor} if cursor else {})})
        assert response.status_code == 200, response.text
        data = response.json()
        TraceRelationPage.model_validate(data)
        assert len(data["items"]) <= query.get("limit", 50)
        assert len(data["edges"]) == len(data["items"])
        for event, edge in zip(data["items"], data["edges"], strict=True):
            assert event["phase"] == data["direction"]
            assert event["kind"] == data["event_kind"]
            assert (edge["from"], edge["to"]) == (
                (event["id"], data["anchor"]["event_id"])
                if data["direction"] == "before"
                else (data["anchor"]["event_id"], event["id"])
            )
            encoded = json.dumps(event)
            assert "demo_private" not in encoded and "ui_test@example.com" not in encoded and "000-00-12" not in encoded
        ids.extend(int(event["id"].split(":")[-1]) for event in data["items"])
        cursor = data["next_cursor"]
        if not cursor:
            assert len(ids) == data["total"]
            return data, ids
        assert cursor not in seen_cursors
        seen_cursors.add(cursor)
        assert len(seen_cursors) < 100


def test_complete_1001_members_both_families_scoped_and_read_only(configured):
    case = make_case(configured, 1000)
    before = fingerprints(configured)
    path = f"/api/trace/incident/{case['incident']}/relations"
    with TestClient(create_app()) as client:
        for direction, family, expected in [
            ("before", "signal_created", case["signals"]),
            ("after", "notification", case["notices"]),
        ]:
            data, ids = walk(client, path, direction=direction, event_kind=family, limit=50)
            assert data["total"] == 1001
            assert len(ids) == len(set(ids)) == 1001 and set(ids) == expected
            explicit = client.get(
                path, params={"direction": direction, "event_kind": family, "run_id": case["own"], "limit": 100}
            )
            assert explicit.status_code == 200 and explicit.json()["total"] == 1001
            source = client.get(
                f"/api/trace/incident/{case['incident']}", params={"run_id": "current", "include": "detail"}
            )
            assert source.status_code == 200
            group = next(
                g
                for g in source.json()["groups"]
                if g["kind"] == family and g.get("anchor", {}).get("ref") == data["anchor"]["ref"]
            )
            assert group["count"] == 1001 and len(group["sample_refs"]) == 3
            assert group["phase"] == direction and group["anchor"] == data["anchor"]
        all_data, all_ids = walk(client, path, direction="after", event_kind="notification", run_id="all", limit=100)
        assert all_data["total"] == 1002 and set(all_ids) == case["all_notices"]
        assert (
            client.get(
                path, params={"direction": "before", "event_kind": "signal_created", "run_id": case["foreign"]}
            ).status_code
            == 404
        )
    assert fingerprints(configured) == before


def test_cursor_context_upper_fence_and_missing_current(configured):
    case = make_case(configured)
    path = f"/api/trace/incident/{case['incident']}/relations"
    query = {"direction": "after", "event_kind": "notification", "limit": 5}
    with TestClient(create_app()) as client:
        first = client.get(path, params=query).json()
        cursor = first["next_cursor"]
        assert cursor
        with psycopg.connect(dsn(configured), autocommit=True) as conn:
            late = conn.execute(
                "insert into notifications(run_id,recipient_type,client_id,incident_id,channel_code,body) values(%s,'client',%s,%s,'chat','T234 later insertion') returning id",
                (case["own"], case["client"], case["incident"]),
            ).fetchone()[0]
        rest = client.get(path, params={**query, "cursor": cursor}).json()
        assert rest["total"] == first["total"]
        assert all(event["id"] != f"EVT-notification:{late}" for event in rest["items"])
        collected = list(first["items"])
        next_cursor = cursor
        while next_cursor:
            page = client.get(path, params={**query, "cursor": next_cursor}).json()
            assert page["total"] == first["total"]
            collected.extend(page["items"])
            next_cursor = page["next_cursor"]
        assert len(collected) == len({event["id"] for event in collected}) == first["total"]
        assert all(event["id"] != f"EVT-notification:{late}" for event in collected)
        empty = client.get(
            f"/api/trace/client/{case['client']}/relations",
            params={"direction": "before", "event_kind": "notification"},
        )
        assert empty.status_code == 200 and empty.json()["total"] == 0
        assert empty.json()["items"] == empty.json()["edges"] == [] and empty.json()["next_cursor"] is None
        for override in ({"direction": "before"}, {"event_kind": "signal_created"}, {"run_id": "all"}):
            assert client.get(path, params={**query, **override, "cursor": cursor}).status_code == 422
        assert (
            client.get(f"/api/trace/client/{case['client']}/relations", params={**query, "cursor": cursor}).status_code
            == 422
        )
        with psycopg.connect(dsn(configured), autocommit=True) as conn:
            conn.execute("update sim_state set current_run_id=null where id=1")
            baseline_ids = {
                row[0]
                for row in conn.execute(
                    "select s.id from signals s join sim_runs r on r.id=s.run_id where s.client_id=%s and r.kind='baseline'",
                    (case["client"],),
                ).fetchall()
            }
        missing = client.get(path, params=query)
        assert missing.status_code == 404
        data, ids = walk(
            client,
            f"/api/trace/client/{case['client']}/relations",
            direction="after",
            event_kind="signal_created",
            run_id="current",
        )
        assert set(ids) == baseline_ids
        empty_scope = client.get(
            f"/api/trace/client/{case['client']}/relations",
            params={"direction": "after", "event_kind": "signal_created", "run_id": ""},
        )
        assert empty_scope.status_code == 200 and empty_scope.json()["total"] == data["total"]
        assert case["foreign_signal"] not in ids


def test_large_fan_page_latency_and_bounded_response(configured):
    case = make_case(configured, 10000)
    samples = []
    with TestClient(create_app()) as client:
        for _ in range(10):
            started = time.perf_counter()
            response = client.get(
                f"/api/trace/incident/{case['incident']}/relations",
                params={"direction": "after", "event_kind": "notification", "limit": 50},
            )
            samples.append((time.perf_counter() - started) * 1000)
            assert response.status_code == 200
            data = response.json()
            assert data["total"] == 10001 and len(data["items"]) == 50 and len(data["edges"]) == 50
            assert len(response.content) < 100_000
        tracemalloc.start()
        try:
            measured = client.get(
                f"/api/trace/incident/{case['incident']}/relations",
                params={"direction": "after", "event_kind": "notification", "limit": 50},
            )
            assert measured.status_code == 200
            _, peak_bytes = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        assert peak_bytes < 8 * 1024 * 1024
    ordered = sorted(samples)
    p95 = ordered[math.ceil(len(ordered) * 0.95) - 1]
    Path("/tmp/vibebashers-t234-fan-perf.json").write_text(
        json.dumps(
            {
                "mode": "actual TestClient/PG, readonly GET, noLLM",
                "members": 10001,
                "page_size": 50,
                "samples_ms": samples,
                "p95_ms": p95,
                "response_items": 50,
                "python_request_peak_bytes": peak_bytes,
            },
            indent=2,
        )
        + "\n"
    )
    assert p95 < 300
