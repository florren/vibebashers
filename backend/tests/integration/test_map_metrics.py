"""B08/B14: экономика по инцидентам на реальной схеме, карта и метрики через HTTP (seeded БД)."""

from __future__ import annotations

import os

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from app.config import get_settings
from app.economics import dcltv
from app.main import create_app
from tests.helpers import dsn


@pytest.mark.integration
@pytest.mark.asyncio
async def test_economics_recompute_and_summary(seeded: str) -> None:
    async with await psycopg.AsyncConnection.connect(dsn(seeded), row_factory=dict_row) as conn:
        n = await dcltv.recompute(conn, only_stale=False, limit=20)
        row = await (await conn.execute("select count(*) as n from incident_economics")).fetchone()
        assert row and int(row["n"]) >= min(n, 1)
        summ = await dcltv.summary(conn, run_id=None, group_by="product")
        assert summ["potential_loss_rub"] >= summ["prevented_loss_rub"] >= 0
        assert summ["calibration_mode"] in ("manual", "simulated")
        one = await (
            await conn.execute("select incident_id from incident_economics order by incident_id limit 1")
        ).fetchone()
        if one:
            res = await dcltv.compute_incident(conn, int(one["incident_id"]))
            assert res and "formula_ru" in res and res["potential_loss_rub"] >= 0
            # повторный расчёт идемпотентен по строке
            again = await (
                await conn.execute(
                    "select count(*) as n from incident_economics where incident_id = %s", (one["incident_id"],)
                )
            ).fetchone()
            assert again and int(again["n"]) == 1


@pytest.mark.integration
def test_map_and_metrics_http(seeded: str) -> None:
    os.environ["DATABASE_URL"] = seeded
    os.environ["APP_ENV"] = "test"
    get_settings.cache_clear()
    try:
        _run_http_checks(seeded)
    finally:
        get_settings.cache_clear()


def _run_http_checks(seeded: str) -> None:
    with TestClient(create_app()) as c:
        heat = c.get("/api/map/heat", params={"layer": "signals", "window_hours": 720, "run_id": "all"})
        assert heat.status_code == 200
        items = heat.json()
        assert len(items) >= 80 and {"region_code", "value", "intensity", "signals"} <= set(items[0])
        assert all(0 <= i["intensity"] <= 1 for i in items)
        zones = c.get("/api/map/zones", params={"run_id": "all"}).json()
        assert {"thresholds", "no_geo_count", "items"} <= set(zones) and all(
            z["zone"] in ("green", "yellow", "red") for z in zones["items"]
        )
        top = max(items, key=lambda i: i["signals"])
        cities = c.get(f"/api/map/regions/{top['region_code']}/cities", params={"window_hours": 720, "run_id": "all"})
        assert cities.status_code == 200
        dash = c.get("/api/metrics/dashboard", params={"window": "all"})
        assert dash.status_code == 200
        d = dash.json()
        assert {"signals_today", "autonomous_share", "sla_compliance_pct", "economics"} <= set(d)
        assert 0 <= d["autonomous_share"] <= 100
        econ = c.get("/api/metrics/economics", params={"group_by": "region", "run_id": "all"}).json()
        assert econ["group_by"] == "region" and isinstance(econ["groups"], list)
        live = c.get("/api/metrics/economics/live", params={"run_id": "all"}).json()
        assert {"run_id", "clv_at_risk_rub", "prevented_rub", "potential_loss_rub", "computed_at"} <= set(live)
        fact = c.get("/api/metrics/economics/fact", params={"run_id": "all"}).json()
        assert {"faults_matrix", "outcomes", "churned", "assumptions_vs_fact"} <= set(fact)
        csv = c.get("/api/metrics/economics/fact/export", params={"format": "csv", "run_id": "all"})
        assert csv.status_code == 200 and csv.headers["content-type"].startswith("text/csv")
        notif = c.get("/api/notifications", params={"limit": 5, "run_id": "all"}).json()
        assert "items" in notif
