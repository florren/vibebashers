"""Холодная статистика не должна превращать связи сигналов в квадратичный scan."""

from __future__ import annotations

import datetime as dt
import json
import math
import time
from collections.abc import Callable, Iterator
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from tests.integration.conftest import _seed, rebuild_schema
from tests.integration.test_cabinet_api import fingerprint


@pytest.fixture(scope="module")
def cold_db(migrated_db: str) -> Iterator[str]:
    rebuild_schema(migrated_db)
    dsn = migrated_db.replace("postgresql+psycopg:", "postgresql:")
    with psycopg.connect(dsn, autocommit=True) as conn:
        # Только scratch fixture: сохраняем отсутствие stats после загрузки,
        # не подменяя planner settings, SQL или production startup.
        conn.execute("ALTER TABLE signals SET (autovacuum_enabled=false)")
    try:
        seeded = _seed(migrated_db, "--profile", "demo", "--clients", "5000")
        assert seeded.returncode == 0, seeded.stderr[-1000:]
        yield migrated_db
    finally:
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute("ALTER TABLE signals RESET (autovacuum_enabled)")


def test_cold_report_preserves_links_without_repeated_scans(
    cold_db: str, monkeypatch: pytest.MonkeyPatch, record_property: Callable[[str, Any], None]
) -> None:
    from app.analytics import cabinet_signals
    from app.main import create_app

    captured: list[tuple[str, Any]] = []
    original = cabinet_signals.fetch_all

    async def observed(conn: Any, sql: str, args: Any = ()) -> Any:
        if not captured:
            captured.append((sql, args))
        return await original(conn, sql, args)

    monkeypatch.setattr(cabinet_signals, "fetch_all", observed)
    with psycopg.connect(cold_db.replace("postgresql+psycopg:", "postgresql:"), autocommit=True) as sql:
        assert sql.execute("SELECT count(*) FROM clients").fetchone()[0] == 5000
        assert sql.execute(
            "SELECT last_analyze,last_autoanalyze FROM pg_stat_user_tables WHERE relname='signals'"
        ).fetchone() == (None, None)
        before = fingerprint(sql)
        samples = []
        with TestClient(create_app()) as client:
            for _ in range(30):
                start = time.perf_counter()
                response = client.get("/api/cabinet/report?product_line=all&period=quarter")
                samples.append((time.perf_counter() - start) * 1000)
                assert response.status_code == 200
            data = response.json()
        assert sorted(samples)[math.ceil(len(samples) * 0.95) - 1] < 300
        # Все связи и ближайший активный deadline сверяем с native таблицами.
        rows = sql.execute(
            "SELECT x.signal_id,i.id,i.public_id,i.status,i.sla_due_sim FROM incident_signals x "
            "JOIN incidents i ON i.id=x.incident_id JOIN signals s ON s.id=x.signal_id AND s.run_id=i.run_id "
            "WHERE s.id=ANY(%s) ORDER BY i.id",
            ([item["id"] for item in data["signals"]],),
        ).fetchall()
        by_signal: dict[int, list[Any]] = {}
        for ident, *row in rows:
            by_signal.setdefault(ident, []).append(row)
        for item in data["signals"]:
            links = by_signal.get(item["id"], [])
            assert item["incidents"] == [
                dict(zip(("id", "public_id", "status"), row[:3], strict=True)) for row in links
            ]
            due = min(
                (row[3] for row in links if row[2] not in ("closed", "resolved", "rejected", "duplicate")), default=None
            )
            assert (dt.datetime.fromisoformat(item["sla_due_sim"]) if item["sla_due_sim"] else None) == due
        assert fingerprint(sql) == before
        sql.execute("BEGIN READ ONLY")
        try:
            plan = sql.execute("EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) " + captured[0][0], captured[0][1]).fetchone()[0][
                0
            ]
        finally:
            sql.execute("ROLLBACK")

        def nodes(node: dict[str, Any]) -> Iterator[dict[str, Any]]:
            yield node
            for child in node.get("Plans", []):
                yield from nodes(child)

        # Бюджет фактической работы, а не конкретный join type: прежний cold plan
        # обрабатывал >1млн строк и повторял Aggregate2813 раз для2813 сигналов.
        budget = max(1, len(data["signals"])) * 2
        assert all(n.get("Actual Rows", 0) * n.get("Actual Loops", 0) <= budget for n in nodes(plan["Plan"]))
        assert sql.execute(
            "SELECT last_analyze,last_autoanalyze FROM pg_stat_user_tables WHERE relname='signals'"
        ).fetchone() == (None, None)

        record_property("cold_report_samples_ms", json.dumps(samples))
        record_property("cold_signal_explain", json.dumps(plan))
        record_property("cold_signal_stats", "last_analyze=NULL,last_autoanalyze=NULL before and after")
