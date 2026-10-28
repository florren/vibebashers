from __future__ import annotations

import asyncio
import datetime as dt
import time

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.ingest import csi
from app.ingest.normalizer import from_csi
from app.ingest.sync_bridge import create_signal_sync
from app.main import create_app
from tests.unit.test_csi_parser import xlsx_bytes

BASE = {
    "csi_no": "CSI-000101",
    "complaint_ru": "Учебная жалоба: долго ждал в очереди",
    "branch_code": "0042",
    "wait_min": "12,5",
    "employee_public_id": "EMP-00003",
}


def test_json_import_duplicate_and_seed_invariant(seeded: str, conn: psycopg.Connection) -> None:
    before = conn.execute("select count(*) from csi_responses").fetchone()[0]
    assert before > 0
    with TestClient(create_app()) as client:
        first = client.post("/api/ingest/csi", json=BASE)
        assert first.status_code == 202, first.text
        body = first.json()
        assert (body["accepted"], body["duplicates"], body["rejected"]) == (1, 0, 0)
        duplicate = client.post("/api/ingest/csi", json=BASE)
        assert duplicate.status_code == 202, duplicate.text
        assert duplicate.json()["duplicates"] == 1
    assert conn.execute("select count(*) from csi_responses").fetchone()[0] == before + 1
    assert (
        conn.execute(
            "select count(*) from signals s left join csi_responses c on c.signal_id=s.id where s.channel_code='csi_survey' and c.signal_id is null"
        ).fetchone()[0]
        == 0
    )
    signal_id = body["items"][0]["signal_id"]
    record = conn.execute(
        "select s.geo,s.meta,cr.wait_min,cr.employee_id,s.received_sim from signals s join csi_responses cr on cr.signal_id=s.id where s.id=%s",
        (signal_id,),
    ).fetchone()
    assert record[0]["vsp_code"] == "0042"
    assert record[1]["csi_meta"]["csi_no"] == BASE["csi_no"]
    assert float(record[2]) == 12.5 and record[3] == 3
    assert record[4] == conn.execute("select sim_time from sim_state where id=1").fetchone()[0]
    assert (
        conn.execute(
            "select status from ingest_messages where source_code='csi' and external_id=%s", (BASE["csi_no"],)
        ).fetchone()[0]
        == "accepted"
    )


def test_partial_report_and_corrected_retry(seeded: str, conn: psycopg.Connection) -> None:
    rows = [
        {**BASE, "csi_no": "CSI-000201"},
        {**BASE, "csi_no": "CSI-000202", "waiting_count": -1},
        {**BASE, "csi_no": "CSI-000203", "branch_code": "missing"},
    ]
    with TestClient(create_app()) as client:
        response = client.post("/api/ingest/csi", json=rows)
        assert response.status_code == 422, response.text
        assert response.headers["content-type"].startswith("application/problem+json")
        report = response.json()["report"]
        assert (report["accepted"], report["rejected"]) == (1, 2)
        assert report["items"][1]["row"] == 2 and report["items"][1]["column"] == "waiting_count"
        assert report["items"][2]["row"] == 3 and report["items"][2]["column"] == "branch_code"
        retry = client.post("/api/ingest/csi", json=[{**BASE, "csi_no": row["csi_no"]} for row in rows])
        assert retry.status_code == 202, retry.text
        assert (retry.json()["accepted"], retry.json()["duplicates"]) == (2, 1)
    assert (
        conn.execute(
            "select count(*) from csi_responses where csi_no=any(%s)", ([row["csi_no"] for row in rows],)
        ).fetchone()[0]
        == 3
    )
    assert (
        conn.execute(
            "select count(*) from ingest_messages where external_id=any(%s) and status='accepted'",
            ([row["csi_no"] for row in rows],),
        ).fetchone()[0]
        == 3
    )


def test_xlsx_partial_report_and_malformed_file(seeded: str) -> None:
    data = xlsx_bytes(
        [
            ["Номер обращения", "Текст обращения", "ВСП", "Время ожидания (мин)"],
            ["CSI-000301", "Учебная жалоба на ожидание", "0042", "2,5"],
            ["CSI-000302", "Учебная жалоба на очередь", "0042", "bad"],
        ]
    )
    with TestClient(create_app()) as client:
        response = client.post("/api/ingest/csi", files={"file": ("sample.xlsx", data)})
        assert response.status_code == 422, response.text
        report = response.json()["report"]
        assert report["accepted"] == 1 and report["rejected"] == 1
        assert report["items"][1]["row"] == 3
        assert report["items"][1]["column"] == "Время ожидания (мин)"
        bad = client.post("/api/ingest/csi", files={"file": ("broken.xlsx", b"not XLSX")})
        assert bad.status_code == 422, bad.text
        assert bad.json()["report"]["items"][0]["row"] == 1


def test_sync_seed_bridge_keeps_outer_transaction(
    seeded: str, conn: psycopg.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    dsn = seeded.replace("postgresql+psycopg://", "postgresql://")
    run_id, sim_time = conn.execute("select current_run_id,sim_time from sim_state where id=1").fetchone()
    with pytest.raises(ValueError, match="autocommit"):
        create_signal_sync(conn, from_csi({**BASE, "csi_no": "CSI-000400"}), run_id=run_id, sim_time=sim_time)
    with psycopg.connect(dsn) as transaction:
        msg = from_csi({**BASE, "csi_no": "CSI-000401"})
        result = create_signal_sync(transaction, msg, run_id=run_id, sim_time=sim_time)
        assert result["status"] == "accepted"
        assert conn.execute("select count(*) from csi_responses where csi_no='CSI-000401'").fetchone()[0] == 0
        transaction.rollback()
    assert conn.execute("select count(*) from csi_responses where csi_no='CSI-000401'").fetchone()[0] == 0

    async def fail(*args, **kwargs):
        raise csi.CsiError("branch_code", "forced rollback")

    monkeypatch.setattr(csi, "persist", fail)
    with psycopg.connect(dsn) as transaction:
        with pytest.raises(csi.CsiError, match="forced rollback"):
            create_signal_sync(
                transaction, from_csi({**BASE, "csi_no": "CSI-000402"}), run_id=run_id, sim_time=sim_time
            )
        assert (
            transaction.execute(
                "select count(*) from signals where meta->'csi_meta'->>'csi_no'='CSI-000402'"
            ).fetchone()[0]
            == 0
        )
    assert conn.execute("select count(*) from ingest_messages where external_id='CSI-000402'").fetchone()[0] == 0


def test_import_1000_rows_under_10_seconds(seeded: str, conn: psycopg.Connection, record_property) -> None:
    rows = [{**BASE, "csi_no": f"CSI-{300000 + i:06d}"} for i in range(1000)]
    with TestClient(create_app()) as client:
        started = time.perf_counter()
        response = client.post("/api/ingest/csi", json=rows)
        elapsed = time.perf_counter() - started
        record_property("import_1000_seconds", elapsed)
        assert response.status_code == 202, response.text[:2000]
        assert response.json()["accepted"] == 1000
        assert elapsed <= 10, f"1000 CSI: {elapsed:.2f}s > 10s"
        duplicate = client.post("/api/ingest/csi", json=rows)
        assert duplicate.status_code == 202 and duplicate.json()["duplicates"] == 1000
    assert (
        conn.execute(
            "select count(*) from csi_responses where csi_no between 'CSI-300000' and 'CSI-300999'"
        ).fetchone()[0]
        == 1000
    )


def test_generic_ingest_cannot_create_orphan_csi(seeded: str, conn: psycopg.Connection) -> None:
    before = conn.execute("select count(*) from signals where channel_code='csi_survey'").fetchone()[0]
    msg = from_csi({**BASE, "csi_no": "CSI-000501"})
    msg.pop("meta")
    with TestClient(create_app()) as client:
        response = client.post("/api/ingest/messages", json=msg, headers={"X-Source-Code": "csi"})
        assert response.status_code == 202, response.text
        assert response.json()["items"][0]["status"] == "rejected"
        assert response.json()["items"][0]["signal_id"] is None
    assert conn.execute("select count(*) from signals where channel_code='csi_survey'").fetchone()[0] == before


async def test_concurrent_uploads_do_not_duplicate_or_deadlock(seeded: str, conn: psycopg.Connection) -> None:
    import httpx

    app = create_app()
    first = [{**BASE, "csi_no": "CSI-000601", "wait_min": -1}, {**BASE, "csi_no": "CSI-000602"}]
    second = [{**BASE, "csi_no": "CSI-000602"}, {**BASE, "csi_no": "CSI-000601"}]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        responses = await asyncio.wait_for(
            asyncio.gather(client.post("/api/ingest/csi", json=first), client.post("/api/ingest/csi", json=second)),
            timeout=10,
        )
    assert sorted(r.status_code for r in responses) == [202, 422]
    reports = [r.json().get("report", r.json()) for r in responses]
    assert sum(r["accepted"] for r in reports) == 2
    assert sum(r["duplicates"] for r in reports) == 1
    assert (
        conn.execute("select count(*) from csi_responses where csi_no in ('CSI-000601','CSI-000602')").fetchone()[0]
        == 2
    )


def test_csi_composite_audit_key(seeded: str, conn: psycopg.Connection) -> None:
    import json

    branch_id = conn.execute("select id from branches where code='0042'").fetchone()[0]
    day = dt.date(2026, 11, 9)
    args = (branch_id, day, "0-5", "0")
    conn.execute(
        "insert into csi_visits_agg(branch_id,day,wait_bucket,redirects_bucket,visits) values (%s,%s,%s,%s,10)", args
    )
    conn.execute(
        "update csi_visits_agg set visits=11 where branch_id=%s and day=%s and wait_bucket=%s and redirects_bucket=%s",
        args,
    )
    conn.execute(
        "delete from csi_visits_agg where branch_id=%s and day=%s and wait_bucket=%s and redirects_bucket=%s", args
    )
    audit = conn.execute("select op,pk from db_activity_log where table_name='csi_visits_agg' order by id").fetchall()
    assert [row[0] for row in audit] == ["INSERT", "UPDATE", "DELETE"]
    assert all(json.loads(row[1]) == [str(branch_id), day.isoformat(), "0-5", "0"] for row in audit)


def test_legacy_seed_backfill_keeps_signal_ids(seeded: str, conn: psycopg.Connection) -> None:
    from app.ingest.sync_bridge import reconcile_seed_sync

    run_id, sim_time = conn.execute("select current_run_id,sim_time from sim_state where id=1").fetchone()
    # Имитируется формат до T-246: CSI-сигнал старого seed ещё не имеет деталей/журнала.
    signal_id = conn.execute(
        'insert into signals(run_id,channel_code,text,received_sim,origin,status,classification,geo) values (%s,\'csi_survey\',\'Старая учебная жалоба\',%s,\'sim\',\'closed\',\'{"llm_source":"seed","product":"debit_card","criticality":"low"}\',\'{"region_code":"63"}\') returning id',
        (run_id, sim_time),
    ).fetchone()[0]
    before = conn.execute("select count(*) from signals").fetchone()[0]
    with psycopg.connect(seeded.replace("postgresql+psycopg://", "postgresql://")) as transaction:
        assert reconcile_seed_sync(transaction, run_id=run_id) == 1
        assert reconcile_seed_sync(transaction, run_id=run_id) == 0
    assert conn.execute("select count(*) from signals").fetchone()[0] == before
    assert (
        conn.execute("select csi_no from csi_responses where signal_id=%s", (signal_id,))
        .fetchone()[0]
        .startswith("CSI-9")
    )
    assert conn.execute(
        "select status,meta->>'csi_seed_backfill' from signals where id=%s", (signal_id,)
    ).fetchone() == ("closed", "true")
    assert (
        conn.execute("select status from ingest_messages where signal_id=%s", (signal_id,)).fetchone()[0] == "accepted"
    )


def test_unknown_personal_fields_are_rejected_and_not_audited(seeded: str, conn: psycopg.Connection) -> None:
    import json

    with TestClient(create_app()) as client:
        response = client.post(
            "/api/ingest/csi", json={**BASE, "csi_no": "CSI-000701", "employee_name": "DO-NOT-PERSIST"}
        )
        assert response.status_code == 422, response.text
    record = conn.execute(
        "select payload,status from ingest_messages where source_code='csi' and external_id='CSI-000701'"
    ).fetchone()
    assert record[1] == "rejected"
    assert "DO-NOT-PERSIST" not in json.dumps(record[0])
    assert conn.execute("select count(*) from csi_responses where csi_no='CSI-000701'").fetchone()[0] == 0
