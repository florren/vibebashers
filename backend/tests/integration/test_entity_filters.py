"""Фильтры по связям выполняются до LIMIT, не расширяют выбранный запуск."""

from contextlib import asynccontextmanager

import psycopg
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from app.api import compliance, engine, finance, ingest
from app.main import create_app
from tests.helpers import dsn
from tests.integration.test_hitl_continuity import make_case


def test_related_codes_filter_engine_and_finance(seeded, conn, monkeypatch):
    @asynccontextmanager
    async def database():
        async with await psycopg.AsyncConnection.connect(dsn(seeded), row_factory=dict_row) as ac:
            yield ac

    for module in (engine, finance, ingest, compliance):
        monkeypatch.setattr(module, "db", database)
    cid = conn.execute("select id from clients order by id limit 1").fetchone()[0]
    old = make_case(conn, seeded, "filter-old", cid)
    new = make_case(conn, seeded, "filter-new", cid)
    conn.execute(
        "update incidents set status='resolved', resolved_sim=created_sim where id in (%s,%s)", (old["iid"], new["iid"])
    )
    with TestClient(create_app()) as client:
        for ref in old["refs"].values():
            response = client.get("/api/agent/runs", params={"q": ref, "run_id": "all", "limit": 1})
            assert response.status_code == 200, response.text
            rows = response.json()["items"]
            assert len(rows) == 1 and rows[0]["signal_id"] == old["sid"], ref
            total = client.get("/api/v1/finance/impact/total", params={"q": ref, "run_id": old["rid"]})
            assert total.status_code == 200, total.text
            assert [r["incident_id"] for r in total.json()["items"]] == [old["iid"]], ref
            assessment = client.get("/api/v1/finance/impact/assessment", params={"q": ref, "run_id": old["rid"]})
            assert assessment.status_code == 200, assessment.text
            combined = client.get(
                "/api/v1/finance/impact/assessment",
                params={"q": ref, "run_id": old["rid"], "product_mode": "include", "product_codes": "debit_card"},
            )
            assert combined.status_code == 200, combined.text
            empty_products = client.get(
                "/api/v1/finance/impact/total",
                params={"q": ref, "run_id": old["rid"], "product_mode": "include", "product_codes": "deposit"},
            )
            assert empty_products.status_code == 200 and empty_products.json()["items"] == [], empty_products.text
        empty = client.get("/api/agent/runs", params={"q": old["refs"]["signal"], "run_id": new["rid"]})
        assert empty.json()["items"] == []
        for endpoint in ["/api/agent/runs", "/api/ingest/transcripts", "/api/compliance/alerts"]:
            response = client.get(endpoint, params={"q": "SIG-999999999", "run_id": "all"})
            assert response.status_code == 200, response.text
            assert (response.json().get("items", []) if isinstance(response.json(), dict) else response.json()) == []


def test_compliance_search_without_client_signal(seeded, conn, monkeypatch):
    @asynccontextmanager
    async def database():
        async with await psycopg.AsyncConnection.connect(dsn(seeded), row_factory=dict_row) as ac:
            yield ac

    monkeypatch.setattr(ingest, "db", database)
    monkeypatch.setattr(compliance, "db", database)
    rid = conn.execute("select id from sim_runs where kind='baseline' limit 1").fetchone()[0]
    emp, branch, emp_ref = conn.execute("select id,branch_id,public_id from employees limit 1").fetchone()
    session = conn.execute(
        "insert into audio_sessions(run_id,branch_id,employee_id,source,stt_provider,diarization_mode,started_sim) values(%s,%s,%s,'transcript','none','manual',now()) returning id,public_id",
        (rid, branch, emp),
    ).fetchone()
    transcript = conn.execute(
        "insert into transcripts(run_id,kind,source,format,turns,received_sim,audio_session_id,employee_id,branch_id) values(%s,'branch_retail','api','json','[]',now(),%s,%s,%s) returning id,public_id",
        (rid, session[0], emp, branch),
    ).fetchone()
    alert = conn.execute(
        "insert into compliance_alerts(session_id,transcript_id) values(%s,%s) returning id",
        (session[0], transcript[0]),
    ).fetchone()[0]
    with TestClient(create_app()) as client:
        for ref in (emp_ref, session[1], transcript[1]):
            rows = client.get("/api/ingest/transcripts", params={"q": ref, "run_id": str(rid)}).json()["items"]
            assert transcript[0] in [row["id"] for row in rows], rows
            rows = client.get("/api/compliance/alerts", params={"q": ref, "run_id": str(rid)}).json()
            assert alert in [row["id"] for row in rows], rows
