"""Страница ограничивает JSON projection до LIMIT и при ещё не обновлённых PG statistics."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.trace import fanout
from tests.helpers import dsn
from tests.integration.test_trace_fanout import configured, make_case  # noqa: F401 (pytest fixture)

pytestmark = pytest.mark.integration


def walk(plan):
    yield plan
    for child in plan.get("Plans", []):
        yield from walk(child)


def test_json_projection_is_bounded_before_statistics_catch_up(request, monkeypatch):
    fixture_url = request.getfixturevalue("configured")
    # Изменяется только изолированная fixture DB; fixture следующего теста
    # пересоздаёт таблицы. ANALYZE/warmup не добавляется в performance gate.
    with psycopg.connect(dsn(fixture_url), autocommit=True) as conn:
        conn.execute("ALTER TABLE notifications SET (autovacuum_enabled=false)")
    case = make_case(fixture_url, 10000)
    captured = []
    original = fanout.fetch_all

    async def capture(conn, statement, args=()):
        captured.append((statement, args))
        return await original(conn, statement, args)

    monkeypatch.setattr(fanout, "fetch_all", capture)
    with TestClient(create_app()) as client:
        response = client.get(
            f"/api/trace/incident/{case['incident']}/relations",
            params={"direction": "after", "event_kind": "notification", "limit": 50},
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 10001 and len(payload["items"]) == 50
    assert len(captured) == 1
    statement, args = captured[0]
    with psycopg.connect(dsn(fixture_url)) as conn:
        conn.execute("SET TRANSACTION READ ONLY")
        stats = conn.execute(
            "SELECT last_analyze,last_autoanalyze FROM pg_stat_all_tables WHERE schemaname='public' AND relname='notifications'"
        ).fetchone()
        assert stats == (None, None)
        explain = conn.execute("EXPLAIN (ANALYZE,VERBOSE,BUFFERS,FORMAT JSON) " + statement, args).fetchone()[0][0]
    projections = [
        node for node in walk(explain["Plan"]) if any("to_jsonb" in value for value in node.get("Output", []))
    ]
    assert projections
    # Инвариант о реально обработанных строках, не о названии CTE/форме SQL.
    assert all(node["Actual Rows"] * node["Actual Loops"] <= 51 for node in projections), [
        (node["Node Type"], node["Actual Rows"], node["Actual Loops"]) for node in projections
    ]
    Path("/tmp/t234-json-projection-budget.json").write_text(
        json.dumps(
            {
                "fanout_source_sha256": hashlib.sha256(Path(fanout.__file__).read_bytes()).hexdigest(),
                "members": 10001,
                "page_limit": 50,
                "projected_rows_max": max(node["Actual Rows"] * node["Actual Loops"] for node in projections),
                "last_analyze": None,
                "last_autoanalyze": None,
                "read_only_explain": True,
                "execution_ms": explain["Execution Time"],
                "plan": explain,
            },
            indent=2,
        )
        + "\n"
    )
