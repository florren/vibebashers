"""Freeze: чтение Fact не пересчитывает деньги, XLSX остаётся настоящим XLSX."""

from contextlib import asynccontextmanager
from io import BytesIO

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app.api import metrics


@pytest.fixture
def fact_client(monkeypatch):
    calls = []

    @asynccontextmanager
    async def read_db():
        calls.append("db")
        yield object()

    async def resolve(conn, requested):
        return None if requested == "all" else 17

    async def one(conn, query, args):
        return {"id": args[0]}

    async def fact(conn, rid, product, system, region):
        calls.append((rid, product, system, region))
        return {
            "outcomes": [
                {
                    "outcome_class": "resolved",
                    "incidents": 2,
                    "potential_loss_rub": 5000.25,
                    "prevented_loss_rub": 1000.5,
                    "realized_loss_rub": 0,
                }
            ],
            "faults_matrix": [
                {
                    "product_code": "deposit",
                    "system_code": "deposit_core",
                    "sim_day": "2026-11-04",
                    "sim_hour": 9,
                    "faults": 1,
                    "operations_affected": 3,
                    "clients_affected": 2,
                    "signals": 1,
                }
            ],
            "churned": [],
            "assumptions_vs_fact": {},
        }

    async def forbidden(*args, **kwargs):
        raise AssertionError("Fact GET must not recompute economics")

    monkeypatch.setattr(metrics, "read_db", read_db)
    monkeypatch.setattr(metrics, "db", read_db)
    monkeypatch.setattr(metrics, "resolve_run_id", resolve)
    monkeypatch.setattr(metrics, "fetch_one", one)
    monkeypatch.setattr(metrics, "_fact", fact)
    monkeypatch.setattr(metrics.dcltv, "recompute", forbidden)
    app = FastAPI()
    app.include_router(metrics.router)
    with TestClient(app) as client:
        yield client, calls


def test_fact_get_uses_saved_economics(fact_client):
    client, calls = fact_client
    response = client.get("/api/metrics/economics/fact", params={"run_id": "17"})
    assert response.status_code == 200
    assert response.json()["outcomes"][0]["potential_loss_rub"] == 5000.25
    assert calls[-1] == (17, None, None, None)


@pytest.mark.parametrize("scope", ["all", "17"])
def test_fact_xlsx_is_excel_file_and_preserves_numbers(fact_client, scope):
    client, calls = fact_client
    response = client.get("/api/metrics/economics/fact/export", params={"run_id": scope, "format": "xlsx"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert response.headers["content-disposition"].endswith('.xlsx"')
    workbook = load_workbook(BytesIO(response.content), read_only=True, data_only=False)
    try:
        rows = list(workbook.active.values)
        assert rows[1][:6] == ("outcome", "resolved", 2, 5000.25, 1000.5, 0)
        assert rows[-1][:8] == ("deposit", "deposit_core", "2026-11-04", 9, 1, 3, 2, 1)
    finally:
        workbook.close()
    assert calls[-1][0] == (None if scope == "all" else 17)


def test_csv_remains_utf8_with_bom(fact_client):
    client, _ = fact_client
    response = client.get("/api/metrics/economics/fact/export?run_id=17&format=csv")
    assert response.headers["content-type"].startswith("text/csv")
    assert response.content.startswith(b"\xef\xbb\xbfsection;key;")
    assert "outcome;resolved;2;5000.25;1000.5;0\r\n" in response.content.decode("utf-8-sig")


@pytest.mark.parametrize("key", ["product", "system", "region_code"])
def test_partial_fact_filters_fail_before_db(fact_client, key):
    client, calls = fact_client
    response = client.get("/api/metrics/economics/fact", params={key: "synthetic"})
    assert response.status_code == 422
    assert "пока не поддерживаются" in response.json()["detail"]
    assert calls == []


@pytest.mark.parametrize("value", ["", "0", "-1", "foo", "1.5", "9223372036854775808"])
@pytest.mark.parametrize(
    "path",
    [
        "/api/metrics/economics/fact",
        "/api/metrics/economics/fact/export",
        "/api/metrics/dashboard",
        "/api/metrics/economics",
    ],
)
def test_invalid_scope_fails_before_db(fact_client, value, path):
    client, calls = fact_client
    response = client.get(path, params={"run_id": value})
    assert response.status_code == 422
    assert calls == []


def test_missing_current_never_becomes_all(fact_client, monkeypatch):
    client, calls = fact_client

    async def missing(conn, requested):
        assert requested == "current"
        return None

    monkeypatch.setattr(metrics, "resolve_run_id", missing)
    response = client.get("/api/metrics/economics/fact")
    assert response.status_code == 200
    assert calls[-1] == (-1, None, None, None)


def test_nonexistent_numeric_scope_is_not_all(fact_client, monkeypatch):
    client, calls = fact_client

    async def missing(*args):
        return None

    monkeypatch.setattr(metrics, "fetch_one", missing)
    response = client.get("/api/metrics/economics/fact?run_id=17")
    assert response.status_code == 404
    assert calls == ["db"]


def test_xlsx_does_not_turn_text_into_formula(fact_client, monkeypatch):
    client, _ = fact_client

    async def fact(*args):
        return {
            "outcomes": [
                {
                    "outcome_class": "=1+1",
                    "incidents": 1,
                    "potential_loss_rub": None,
                    "prevented_loss_rub": None,
                    "realized_loss_rub": None,
                }
            ],
            "faults_matrix": [],
        }

    monkeypatch.setattr(metrics, "_fact", fact)
    response = client.get("/api/metrics/economics/fact/export?run_id=17&format=xlsx")
    workbook = load_workbook(BytesIO(response.content), read_only=True, data_only=False)
    try:
        cell = workbook.active["B2"]
        assert cell.value == "=1+1" and cell.data_type == "s"
        assert workbook.active["D2"].value is None
    finally:
        workbook.close()


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({}, 17),
        ({"window": "all"}, None),
        ({"window": "all", "run_id": "17"}, 17),
        ({"window": "all", "run_id": "current"}, 17),
        ({"window": "run", "run_id": "all"}, None),
    ],
)
def test_explicit_dashboard_run_has_priority_over_window(fact_client, monkeypatch, params, expected):
    client, calls = fact_client

    async def dashboard(conn, *, rid, window):
        calls.append(("dashboard", rid, window))
        return {"signals_total": 0}

    monkeypatch.setattr(metrics, "dashboard", dashboard)
    assert client.get("/api/metrics/dashboard", params=params).status_code == 200
    assert calls[-1][0:2] == ("dashboard", expected)


def test_dashboard_missing_current_never_calls_reader_or_producer(fact_client, monkeypatch):
    client, calls = fact_client

    async def missing(*args):
        return None

    async def forbidden(*args, **kwargs):
        raise AssertionError("Missing current must not read global dashboard")

    monkeypatch.setattr(metrics, "resolve_run_id", missing)
    monkeypatch.setattr(metrics, "dashboard", forbidden)
    response = client.get("/api/metrics/dashboard")
    assert response.status_code == 200 and response.json() == {}
    assert calls == ["db"]


def test_economics_missing_current_disables_legacy_refresh(fact_client, monkeypatch):
    client, calls = fact_client

    async def missing(*args):
        return None

    async def summary(conn, *, run_id, group_by, window, refresh):
        calls.append((run_id, refresh))
        return {"groups": []}

    monkeypatch.setattr(metrics, "resolve_run_id", missing)
    monkeypatch.setattr(metrics.dcltv, "summary", summary)
    assert client.get("/api/metrics/economics").status_code == 200
    assert calls[-1] == (-1, False)
