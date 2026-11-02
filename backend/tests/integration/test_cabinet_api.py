"""T-241: реальный PostgreSQL/API, scope и saved economics без ORM/LLM/write."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import psycopg
import pytest
import yaml
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from tests.integration.conftest import _seed

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def cabinet_db(migrated_db: str) -> Iterator[str]:
    seeded = _seed(migrated_db, "--profile", "demo", "--clients", "5000")
    assert seeded.returncode == 0, seeded.stderr[-1000:]
    with psycopg.connect(migrated_db.replace("postgresql+psycopg:", "postgresql:"), autocommit=True) as conn:
        assert conn.execute("select version_num from alembic_version").fetchone()[0] == "0018"
    yield migrated_db


@pytest.fixture
def client(cabinet_db: str) -> Iterator[TestClient]:
    from app.main import create_app

    with TestClient(create_app()) as client:
        yield client


@pytest.fixture
def sql(cabinet_db: str) -> Iterator[Any]:
    with psycopg.connect(cabinet_db.replace("postgresql+psycopg:", "postgresql:"), autocommit=True) as conn:
        yield conn


@contextmanager
def preset(sql: Any, visibility: str, lines: list[str] | None = None) -> Iterator[None]:
    old = sql.execute("select value from settings where key='cabinet'").fetchone()
    from psycopg.types.json import Jsonb

    sql.execute(
        "insert into settings(key,value) values('cabinet',%s) on conflict(key) do update set value=excluded.value",
        (Jsonb({"visibility": visibility, "product_head_lines": lines or []}),),
    )
    try:
        yield
    finally:
        if old:
            sql.execute("update settings set value=%s where key='cabinet'", (Jsonb(old[0]),))
        else:
            sql.execute("delete from settings where key='cabinet'")


def assert_schema(data: Any, name: str) -> None:
    contract = yaml.safe_load((ROOT / "contracts/api/openapi.yaml").read_text())
    Draft202012Validator({"$ref": "#/components/schemas/" + name, "components": contract["components"]}).validate(data)


def fingerprint(sql: Any) -> dict[str, tuple[Any, ...]]:
    tables = [x[0] for x in sql.execute("select tablename from pg_tables where schemaname='public' order by tablename")]
    from psycopg import sql as pgsql

    return {
        table: sql.execute(
            pgsql.SQL(
                "select count(*),md5(coalesce(string_agg(md5(row_to_json(t)::text),'' order by md5(row_to_json(t)::text)),'')) from {} t"
            ).format(pgsql.Identifier(table))
        ).fetchone()
        for table in tables
    }


def test_actual_shapes_read_only_and_coverage(client: TestClient, sql: Any) -> None:
    before = fingerprint(sql)
    for endpoint, schema in [
        ("roles", "CabinetRoles"),
        ("cabinet/overview", "CabinetOverview"),
        ("cabinet/signals", "CabinetSignals"),
    ]:
        response = client.get("/api/" + endpoint)
        assert response.status_code == 200
        assert_schema(response.json(), schema)
    data = client.get("/api/cabinet/overview?period=month").json()
    assert len(data["daily"]) == 30
    assert data["kpi"]["mapped"] < data["kpi"]["signals"]  # T240 unknowns не приписываем направлению.
    assert data["kpi"]["economics_known"] <= data["kpi"]["incidents"]
    assert len(data["top_regions"]) <= 5
    assert before == fingerprint(sql)


@pytest.mark.parametrize("endpoint", ["overview", "signals", "report"])
@pytest.mark.parametrize("chosen", ["other", "all"])
def test_strict_no_foreign_path(client: TestClient, sql: Any, endpoint: str, chosen: str) -> None:
    lines = [x[0] for x in sql.execute("select code from product_lines order by code limit 2")]
    with preset(sql, "strict"):
        response = client.get(
            "/api/cabinet/" + endpoint,
            params={"product_line": lines[1] if chosen == "other" else "all"},
            headers={"X-Cx-Role": "product_manager", "X-Cx-Product-Line": lines[0]},
        )
        assert response.status_code == 403
        assert "signals" not in response.json()


def test_soft_override_and_strict_catalog(client: TestClient, sql: Any) -> None:
    line = sql.execute("select code from product_lines order by code limit 1").fetchone()[0]
    headers = {"X-Cx-Role": "product_manager", "X-Cx-Product-Line": line}
    with preset(sql, "soft"):
        scoped = client.get("/api/cabinet/overview?period=month", headers=headers).json()
        bank = client.get("/api/cabinet/overview?period=month&product_line=all", headers=headers).json()
        assert scoped["scope"]["product_lines"] == [line]
        assert bank["scope"]["product_lines"] is None
        assert scoped["kpi"]["signals"] < bank["kpi"]["signals"]
    with preset(sql, "strict"):
        scoped = client.get("/api/cabinet/overview", headers=headers).json()
        assert [x["code"] for x in scoped["product_lines"]] == [line]
        rows = client.get("/api/cabinet/signals?period=quarter", headers=headers).json()
        assert all(x["product_line_code"] == line for x in rows["items"])


def test_product_head_empty_scope_and_missing_manager(client: TestClient, sql: Any) -> None:
    with preset(sql, "strict"):
        for endpoint in ["overview", "signals"]:
            assert client.get("/api/cabinet/" + endpoint, headers={"X-Cx-Role": "product_manager"}).status_code == 403
        overview = client.get("/api/cabinet/overview", headers={"X-Cx-Role": "product_head"}).json()
        assert overview["product_lines"] == [] and overview["kpi"]["signals"] == 0
        assert overview["kpi"]["potential_loss_rub"] is None


def test_sort_filters_pagination_privacy(client: TestClient, sql: Any) -> None:
    for sort in ["date", "level", "region"]:
        for direction in ["asc", "desc"]:
            a = client.get(
                "/api/cabinet/signals", params={"period": "quarter", "sort": sort, "direction": direction, "limit": 7}
            ).json()
            b = client.get(
                "/api/cabinet/signals",
                params={
                    "period": "quarter",
                    "sort": sort,
                    "direction": direction,
                    "limit": 7,
                    "offset": a["next_offset"],
                },
            ).json()
            assert len(a["items"]) == len(b["items"]) == 7
            assert not {x["id"] for x in a["items"]} & {x["id"] for x in b["items"]}
            for item in a["items"]:
                assert "text" not in item and "meta" not in item and "external_contact" not in item
    sample = client.get("/api/cabinet/signals?period=quarter&limit=1").json()["items"][0]
    params = {
        "period": "quarter",
        "region": sample["region_code"],
        "status": sample["status"],
        "channel": sample["channel_code"],
    }
    data = client.get("/api/cabinet/signals", params={k: v for k, v in params.items() if v is not None}).json()
    assert all(x["channel_code"] == sample["channel_code"] and x["status"] == sample["status"] for x in data["items"])
    red = client.get("/api/cabinet/signals?period=quarter&red_words=true").json()
    assert all("red_word" in x["flags"] for x in red["items"])


@pytest.mark.parametrize(
    "query",
    [
        "run_id=²",
        "run_id=٢",
        "run_id=9223372036854775808",
        "run_id=",
        "sort=arbitrary",
        "limit=201",
        "offset=-1",
        "period=year",
    ],
)
def test_query_boundaries(client: TestClient, query: str) -> None:
    assert client.get("/api/cabinet/signals?" + query).status_code == 422


def test_all_current_and_foreign_run(client: TestClient, sql: Any) -> None:
    pointer = sql.execute("select current_run_id from sim_state where id=1").fetchone()[0]
    foreign = sql.execute(
        "insert into sim_runs(kind,label,seed,started_sim) select 'live','T241 scope fixture',42,sim_time from sim_state where id=1 returning id"
    ).fetchone()[0]
    original = sql.execute(
        "select s.id,s.run_id from signals s cross join sim_state st where st.id=1 and s.received_sim<=st.sim_time order by s.received_sim desc,s.id desc limit 1"
    ).fetchone()
    try:
        sql.execute("update signals set run_id=%s where id=%s", (foreign, original[0]))
        sql.execute("update sim_state set current_run_id=null where id=1")
        current = client.get("/api/cabinet/signals?period=quarter&limit=200").json()
        assert all(x["run_id"] != foreign for x in current["items"])
        scoped = client.get(
            "/api/cabinet/signals", params={"period": "quarter", "run_id": foreign, "limit": 200}
        ).json()
        assert original[0] in {x["id"] for x in scoped["items"]}
        assert client.get("/api/cabinet/signals?period=quarter&run_id=all").json()["total"] > current["total"]
    finally:
        sql.execute("update signals set run_id=%s where id=%s", (original[1], original[0]))
        sql.execute("update sim_state set current_run_id=%s where id=1", (pointer,))
        sql.execute("delete from sim_runs where id=%s", (foreign,))


def test_saved_economics_deduplicates_signal_fanout(client: TestClient, sql: Any) -> None:
    line = sql.execute("select code from product_lines order by code limit 1").fetchone()[0]
    # Seed намеренно не материализует экономику. Только подготовка fixture явно
    # вызывает реальный producer; проверяемые GET его не вызывают и не пишут.
    import asyncio
    import os

    from psycopg.rows import dict_row

    from app.economics.dcltv import compute_incident

    async def prepare(ids: list[int]) -> None:
        async with await psycopg.AsyncConnection.connect(
            os.environ["DATABASE_URL_TEST"].replace("postgresql+psycopg:", "postgresql:"), row_factory=dict_row
        ) as connection:
            for incident_id in ids:
                result = await compute_incident(connection, incident_id)
                assert result is not None

    incident = sql.execute("select id,run_id from incidents order by id limit 1").fetchone()
    assert incident is not None
    # Явная тестовая связь трёх существующих сигналов с одним инцидентом.
    samples = sql.execute(
        "select id,product_line_code from signals where run_id=%s and id not in (select signal_id from incident_signals where incident_id=%s) order by id limit 3",
        (incident[1], incident[0]),
    ).fetchall()
    try:
        for sid, _ in samples:
            sql.execute("update signals set product_line_code=%s where id=%s", (line, sid))
            sql.execute(
                "insert into incident_signals(incident_id,signal_id,link_type,linked_sim) select %s,%s,'primary',sim_time from sim_state where id=1",
                (incident[0], sid),
            )
        unknown = client.get("/api/cabinet/overview", params={"product_line": line, "period": "quarter"}).json()
        assert unknown["kpi"]["potential_loss_rub"] is None
        ids = [
            x[0]
            for x in sql.execute(
                "select distinct i.id from incidents i join incident_signals x on x.incident_id=i.id join signals s on s.id=x.signal_id and s.run_id=i.run_id where s.product_line_code=%s",
                (line,),
            )
        ]
        asyncio.run(prepare(ids))
        data = client.get("/api/cabinet/overview", params={"product_line": line, "period": "quarter"}).json()
        expected = sql.execute(
            "select count(*),sum(ie.potential_loss_rub),sum(ie.prevented_loss_rub) from incident_economics ie where ie.incident_id in (select distinct x.incident_id from incident_signals x join signals s on s.id=x.signal_id where s.product_line_code=%s)",
            (line,),
        ).fetchone()
        assert data["kpi"]["incidents"] == expected[0]
        assert data["kpi"]["potential_loss_rub"] == pytest.approx(float(expected[1]))
        assert data["kpi"]["prevented_loss_rub"] == pytest.approx(float(expected[2]))
        before = fingerprint(sql)
        assert (
            client.get("/api/cabinet/overview", params={"product_line": line, "period": "quarter"}).status_code == 200
        )
        assert before == fingerprint(sql)
    finally:
        for sid, original in samples:
            sql.execute("delete from incident_signals where incident_id=%s and signal_id=%s", (incident[0], sid))
            sql.execute("update signals set product_line_code=%s where id=%s", (original, sid))


def test_bank_saved_economics_includes_unknown_direction(client: TestClient, sql: Any) -> None:
    data = client.get("/api/cabinet/overview?product_line=all&period=quarter").json()
    expected = sql.execute(
        "select count(*),count(ie.incident_id),sum(ie.potential_loss_rub),sum(ie.prevented_loss_rub) from incidents i left join incident_economics ie on ie.incident_id=i.id"
    ).fetchone()
    assert data["kpi"]["incidents"] == expected[0]
    assert data["kpi"]["economics_known"] == expected[1]
    if expected[0] == expected[1]:
        assert data["kpi"]["potential_loss_rub"] == pytest.approx(float(expected[2]))
        assert data["kpi"]["prevented_loss_rub"] == pytest.approx(float(expected[3]))
    else:
        assert data["kpi"]["potential_loss_rub"] is None


def test_explain_has_no_correlated_aggregate_loops(sql: Any) -> None:
    plan = sql.execute(
        "explain (analyze,buffers,format json) select distinct i.id,i.potential_loss_rub from v_cabinet_incident_facts i where i.product_line_code=%s",
        ("deposits",),
    ).fetchone()[0][0]

    def walk(node: dict[str, Any]) -> Iterator[dict[str, Any]]:
        yield node
        for child in node.get("Plans", []):
            yield from walk(child)

    nodes = list(walk(plan["Plan"]))
    assert not any(n.get("Parent Relationship") == "SubPlan" for n in nodes)
    assert all(
        n["Actual Loops"] == 1 for n in nodes if n["Node Type"] in ("Aggregate", "HashAggregate", "GroupAggregate")
    )


def test_new_manual_status_audit_role_and_invalid_header(client: TestClient, sql: Any) -> None:
    incident = sql.execute("select id,priority from incidents order by id limit 1").fetchone()
    before = fingerprint(sql)
    invalid = client.post(
        f"/api/incidents/{incident[0]}/actions",
        json={"action": "change_priority", "priority": incident[1]},
        headers={"X-Cx-Role": "untrusted"},
    )
    assert invalid.status_code == 422 and before == fingerprint(sql)
    old_max = sql.execute("select coalesce(max(id),0) from incident_status_history").fetchone()[0]
    response = client.post(
        f"/api/incidents/{incident[0]}/actions",
        json={"action": "change_priority", "priority": incident[1], "actor": "T241 fixture label"},
        headers={"X-Cx-Role": "product_manager"},
    )
    assert response.status_code == 200
    actual = sql.execute(
        "select actor_ref,actor_role from incident_status_history where incident_id=%s and id>%s",
        (incident[0], old_max),
    ).fetchall()
    assert actual == [("T241 fixture label", "product_manager")]
    sql.execute("delete from incident_status_history where incident_id=%s and id>%s", (incident[0], old_max))


def test_new_human_decision_role_is_not_decided_by(client: TestClient, sql: Any) -> None:
    decision = sql.execute(
        "insert into human_decisions(sim_run_id,requested_sim,reason,agent_proposal,options) select current_run_id,sim_time,'T241 explicit audit fixture','{}','[]' from sim_state where id=1 returning id,actor_role"
    ).fetchone()
    assert decision[1] is None
    try:
        response = client.post(
            f"/api/hitl/{decision[0]}",
            json={"decision": "reject", "decided_by": "T241 fixture label", "comment": "explicit integration fixture"},
            headers={"X-Cx-Role": "compliance_officer"},
        )
        assert response.status_code == 200
        assert response.json()["actor_role"] == "compliance_officer"
        assert sql.execute(
            "select decided_by,actor_role from human_decisions where id=%s", (decision[0],)
        ).fetchone() == ("T241 fixture label", "compliance_officer")
    finally:
        sql.execute("delete from human_decisions where id=%s", (decision[0],))


def test_actual_18_reapply_and_additive_downgrade_preserve_audit(cabinet_db: str, sql: Any) -> None:
    import subprocess
    import sys

    migration = (ROOT / "contracts/db/migrations/0018_cabinet_scope.sql").read_text()
    before = fingerprint(sql)
    sql.execute(migration)
    sql.execute(migration)
    assert before == fingerprint(sql)
    audit = sql.execute("select id,actor_role from incident_status_history order by id limit 1").fetchone()
    assert audit is not None
    sql.execute("update incident_status_history set actor_role='admin' where id=%s", (audit[0],))
    try:
        down = subprocess.run(
            [sys.executable, "-m", "alembic", "downgrade", "0017"], cwd=ROOT / "backend", capture_output=True, text=True
        )
        assert down.returncode == 0, down.stderr[-1000:]
        assert sql.execute(
            "select to_regclass('v_cabinet_signal_facts'),to_regclass('v_cabinet_incident_facts')"
        ).fetchone() == (None, None)
        assert (
            sql.execute("select actor_role from incident_status_history where id=%s", (audit[0],)).fetchone()[0]
            == "admin"
        )
        up = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT / "backend", capture_output=True, text=True
        )
        assert up.returncode == 0, up.stderr[-1000:]
        assert sql.execute("select version_num from alembic_version").fetchone()[0] == "0018"
        assert (
            sql.execute("select actor_role from incident_status_history where id=%s", (audit[0],)).fetchone()[0]
            == "admin"
        )
        assert sql.execute("select to_regclass('v_cabinet_signal_facts') is not null").fetchone()[0]
    finally:
        sql.execute("update incident_status_history set actor_role=%s where id=%s", (audit[1], audit[0]))


def test_client_coverage_does_not_turn_anonymous_signals_into_zero_affected(client: TestClient, sql: Any) -> None:
    line = sql.execute(
        "select product_line_code from signals where product_line_code is not null group by 1 order by count(*) limit 1"
    ).fetchone()[0]
    sample = sql.execute(
        "select geo->>'region_code' from signals where product_line_code=%s and geo->>'region_code' is not null limit 1",
        (line,),
    ).fetchone()[0]
    rows = sql.execute(
        "select id,client_id from signals where product_line_code=%s and geo->>'region_code'=%s", (line, sample)
    ).fetchall()
    known_client = sql.execute("select id from clients order by id limit 1").fetchone()[0]

    def region() -> dict[str, Any]:
        data = client.get("/api/cabinet/overview", params={"product_line": line, "period": "quarter"}).json()
        return next(row for row in data["regions"] if row["code"] == sample)

    try:
        for sid, _ in rows:
            sql.execute("update signals set client_id=%s where id=%s", (known_client, sid))
        complete = region()
        assert complete["affected_clients"] == complete["identified_clients"] == 1
        assert complete["identified_signals"] == complete["signals"]
        sql.execute("update signals set client_id=null where id=%s", (rows[0][0],))
        partial = region()
        assert partial["affected_clients"] is None
        assert partial["identified_signals"] < partial["signals"]
        empty = next(
            row
            for row in client.get("/api/cabinet/overview", params={"product_line": line, "period": "quarter"}).json()[
                "regions"
            ]
            if row["signals"] == 0
        )
        assert empty["affected_clients"] == empty["identified_signals"] == empty["identified_clients"] == 0
        before = fingerprint(sql)
        region()
        assert before == fingerprint(sql)
    finally:
        for sid, original in rows:
            sql.execute("update signals set client_id=%s where id=%s", (original, sid))


def test_csi_only_counts_observed_quality_without_assigning_global_visits(client: TestClient, sql: Any) -> None:
    row = sql.execute(
        "select id,channel_code,product_line_code from signals where product_line_code is not null and id not in(select signal_id from csi_responses) limit 1"
    ).fetchone()
    previous = client.get("/api/cabinet/overview", params={"product_line": row[2], "period": "quarter"}).json()["csi"]
    sql.execute("update signals set channel_code='csi_survey' where id=%s", (row[0],))
    sql.execute(
        "insert into csi_responses(signal_id,csi_no,complaint_ru) values(%s,'T241-CSI-QUALITY','explicit quality fixture')",
        (row[0],),
    )
    try:
        data = client.get("/api/cabinet/overview", params={"product_line": row[2], "period": "quarter"}).json()["csi"]
        assert data["responses"] == previous["responses"] + 1
        assert data["branch_known"] == previous["branch_known"]
        assert data["wait_known"] == previous["wait_known"]
        assert data["branches"] is None
        assert data["average_wait_min"] == previous["average_wait_min"]
        branch = sql.execute("select id from branches order by id limit 1").fetchone()[0]
        sql.execute("update csi_responses set branch_id=%s,wait_min=7.5 where signal_id=%s", (branch, row[0]))
        data = client.get("/api/cabinet/overview", params={"product_line": row[2], "period": "quarter"}).json()["csi"]
        assert data["branch_known"] == previous["branch_known"] + 1
        assert data["wait_known"] == previous["wait_known"] + 1
        expected_wait = ((previous["average_wait_min"] or 0) * previous["wait_known"] + 7.5) / data["wait_known"]
        assert data["average_wait_min"] == pytest.approx(expected_wait)
        if data["branch_known"] < data["responses"]:
            assert data["branches"] is None
        else:
            assert data["branches"] >= 1
    finally:
        sql.execute("delete from csi_responses where signal_id=%s", (row[0],))
        sql.execute("update signals set channel_code=%s where id=%s", (row[1], row[0]))


def test_unknown_source_codes_are_one_honest_bucket(client: TestClient, sql: Any) -> None:
    from psycopg.types.json import Jsonb

    rows = sql.execute("select id,meta from signals order by id desc limit 2").fetchall()
    try:
        for n, (sid, meta) in enumerate(rows):
            sql.execute(
                "update signals set meta=%s where id=%s",
                (Jsonb({**meta, "source_platform": f"unknown_fixture_{n}"}), sid),
            )
        data = client.get("/api/cabinet/overview?period=quarter&product_line=all").json()
        unknown = [row for row in data["sources"] if row["platform"] is None]
        assert len(unknown) == 1 and unknown[0]["signals"] >= 2
        assert sum(row["signals"] for row in data["sources"]) == data["kpi"]["signals"]
    finally:
        for sid, meta in rows:
            sql.execute("update signals set meta=%s where id=%s", (Jsonb(meta), sid))


def test_actual_demo_5000_overview_p95_includes_first_get(client: TestClient, sql: Any) -> None:
    import math
    import time

    assert sql.execute("select count(*) from clients").fetchone()[0] == 5000
    assert sql.execute("select value->>'profile' from settings where key='seed_done'").fetchone()[0] == "demo"
    before = fingerprint(sql)
    samples = []
    for _ in range(25):
        start = time.perf_counter()
        response = client.get("/api/cabinet/overview?period=quarter&product_line=all")
        samples.append((time.perf_counter() - start) * 1000)
        assert response.status_code == 200
    p95 = sorted(samples)[math.ceil(len(samples) * 0.95) - 1]
    assert p95 < 300, {"p95_ms": p95, "first_ms": samples[0], "samples": len(samples)}
    assert before == fingerprint(sql)


@pytest.mark.parametrize("manual", [True, False])
def test_compliance_manual_preset_and_automatic_unknown_preserve_legacy_labels(
    client: TestClient, sql: Any, manual: bool
) -> None:
    import asyncio
    import os

    from psycopg.rows import dict_row

    from app.compliance.session import ComplianceService

    incident = sql.execute("select id,status,updated_at from incidents order by id limit 1").fetchone()
    run, now = sql.execute("select current_run_id,sim_time from sim_state where id=1").fetchone()
    branch, employee = sql.execute("select branch_id,id from employees order by id limit 1").fetchone()
    decision = sql.execute(
        "insert into human_decisions(sim_run_id,incident_id,requested_sim,reason,agent_proposal,options) values(%s,%s,%s,'T241 compliance audit fixture','{}','[]') returning id",
        (run, incident[0], now),
    ).fetchone()[0]
    session = sql.execute(
        "insert into audio_sessions(run_id,branch_id,employee_id,source,stt_provider,diarization_mode,started_sim) values(%s,%s,%s,'transcript','none','manual',%s) returning id",
        (run, branch, employee, now),
    ).fetchone()[0]
    alert = sql.execute(
        "insert into compliance_alerts(session_id,incident_id,human_decision_id) values(%s,%s,%s) returning id",
        (session, incident[0], decision),
    ).fetchone()[0]
    old_max = sql.execute("select coalesce(max(id),0) from incident_status_history").fetchone()[0]
    sql.execute("update incidents set status='awaiting_human' where id=%s", (incident[0],))
    label = "T241 branch label" if manual else "demo-agent:T241"
    try:
        if manual:
            response = client.post(
                f"/api/compliance/alerts/{alert}/ack",
                json={"decision": "false_positive"},
                headers={"X-Role": label, "X-Cx-Role": "compliance_officer"},
            )
            assert response.status_code == 200
        else:

            async def acknowledge() -> None:
                async with await psycopg.AsyncConnection.connect(
                    os.environ["DATABASE_URL_TEST"].replace("postgresql+psycopg:", "postgresql:"), row_factory=dict_row
                ) as connection:
                    service = ComplianceService(
                        connection,
                        run_id=run,
                        sim_time=now,
                        chain=client.app.state.llm_chain,
                        profile=client.app.state.llm_profile,
                    )
                    result = await service.ack_alert(alert, decision="false_positive", by=label)
                    assert result is not None

            asyncio.run(acknowledge())
        expected = "compliance_officer" if manual else None
        assert sql.execute(
            "select decided_by,actor_role,decision from human_decisions where id=%s", (decision,)
        ).fetchone() == (label, expected, "reject")
        assert sql.execute(
            "select actor_ref,actor_role,to_status from incident_status_history where incident_id=%s and id>%s",
            (incident[0], old_max),
        ).fetchall() == [(label, expected, "rejected")]
    finally:
        sql.execute("delete from compliance_alerts where id=%s", (alert,))
        sql.execute("delete from audio_sessions where id=%s", (session,))
        sql.execute("delete from human_decisions where id=%s", (decision,))
        sql.execute("delete from incident_status_history where incident_id=%s and id>%s", (incident[0], old_max))
        sql.execute("update incidents set status=%s,updated_at=%s where id=%s", (incident[1], incident[2], incident[0]))


def test_compliance_preset_is_existing_type_or_and_explicit_false_clears_it(client: TestClient, sql: Any) -> None:
    from psycopg.types.json import Jsonb

    line = sql.execute(
        "select product_line_code from signals where product_line_code is not null group by 1 having count(*)>=4 order by 1 limit 1"
    ).fetchone()[0]
    rows = sql.execute(
        "select id,classification,flags,red_words from signals where product_line_code=%s and id not in(select signal_id from incident_signals) order by received_sim desc,id desc limit 4",
        (line,),
    ).fetchall()
    assert len(rows) == 4
    incident = sql.execute("select id,incident_type from incidents order by id limit 1").fetchone()
    try:
        for index, (sid, classification, _, _) in enumerate(rows):
            sql.execute(
                "update signals set classification=%s,flags=%s,red_words=%s where id=%s",
                (
                    Jsonb(
                        {**(classification or {}), "signal_type": "legal_regulatory" if index == 1 else "info_request"}
                    ),
                    ["red_word"] if index == 0 else [],
                    ["суд"] if index == 0 else [],
                    sid,
                ),
            )
        sql.execute("update incidents set incident_type='misselling' where id=%s", (incident[0],))
        sql.execute(
            "insert into incident_signals(incident_id,signal_id,link_type,linked_sim) select %s,%s,'primary',sim_time from sim_state where id=1",
            (incident[0], rows[2][0]),
        )
        headers = {"X-Cx-Role": "compliance_officer"}
        params = {"product_line": line, "period": "quarter", "limit": 200}
        candidate_ids = {row[0] for row in rows}

        def selected(extra: dict[str, Any]) -> set[int]:
            response = client.get("/api/cabinet/signals", headers=headers, params={**params, **extra})
            assert response.status_code == 200
            return {row["id"] for row in response.json()["items"]} & candidate_ids

        assert selected({}) == {row[0] for row in rows[:3]}
        assert selected({"red_words": "true"}) == {rows[0][0]}
        assert selected({"red_words": "false"}) == candidate_ids
        stats = client.get(
            "/api/cabinet/overview", headers=headers, params={"product_line": line, "period": "quarter"}
        ).json()["kpi"]
        assert (
            stats
            == client.get("/api/cabinet/overview", params={"product_line": line, "period": "quarter"}).json()["kpi"]
        )
        roles = client.get("/api/roles").json()["items"]
        assert [row["code"] for row in roles if row["default_compliance_filter"]] == ["compliance_officer"]
    finally:
        sql.execute("delete from incident_signals where incident_id=%s and signal_id=%s", (incident[0], rows[2][0]))
        sql.execute("update incidents set incident_type=%s where id=%s", (incident[1], incident[0]))
        for sid, classification, flags, words in rows:
            sql.execute(
                "update signals set classification=%s,flags=%s,red_words=%s where id=%s",
                (Jsonb(classification) if classification is not None else None, flags, words, sid),
            )


@pytest.mark.parametrize(("origin", "visible"), [(None, True), ("sim", True), ("proactive", False)])
def test_customer_fact_actual_projection_retains_legacy_null_without_weakening_ddl(
    sql: Any, origin: str | None, visible: bool
) -> None:
    from psycopg import sql as pgsql

    definition = sql.execute("select pg_get_viewdef('v_cabinet_signal_facts'::regclass,true)").fetchone()[0]
    # Canonical origin NOT NULL остаётся. CTE исполняет фактическую view-проекцию
    # над nullable legacy shape без изменения таблиц/constraints или записи данных.
    assert "public.signals" not in definition
    assert "is distinct from" in definition.lower()
    projection = pgsql.SQL("""with signals as (
        select id,public_id,run_id,product_line_code,received_sim,sentiment,classification,
        geo,channel_code,meta,client_id,flags,red_words,status,%s::text as origin
        from public.signals order by id limit 1)
        select count(*) from ({}) actual""").format(pgsql.SQL(definition.rstrip().rstrip(";")))
    assert sql.execute(projection, (origin,)).fetchone()[0] == int(visible)


def test_service_anchor_is_not_customer_evidence_but_real_incident_and_trace_remain(
    client: TestClient, sql: Any
) -> None:
    row = sql.execute("""select s.id,s.origin,s.client_id,s.channel_code,s.product_line_code
        from signals s where s.product_line_code is not null
        and s.received_sim <= (select sim_time from sim_state where id=1)
        and s.run_id=(select id from sim_runs where kind='baseline' order by id limit 1)
        order by s.received_sim desc,s.id desc limit 1""").fetchone()
    assert row is not None
    sid, origin, customer, channel, line = row
    incident = sql.execute(
        "select i.id from incidents i join signals s on s.run_id=i.run_id where s.id=%s order by i.id limit 1", (sid,)
    ).fetchone()
    assert incident is not None
    linked = sql.execute(
        "select count(*) from incident_signals where incident_id=%s and signal_id=%s", (incident[0], sid)
    ).fetchone()[0]
    # Связь fixture явная: seed customer projection не обязан иметь incident_signals.
    sql.execute(
        "insert into incident_signals(incident_id,signal_id,linked_sim) select %s,%s,sim_time from sim_state where id=1 on conflict do nothing",
        (incident[0], sid),
    )
    import asyncio
    import os

    from psycopg.rows import dict_row

    from app.economics.dcltv import compute_incident

    async def materialize_fixture() -> None:
        async with await psycopg.AsyncConnection.connect(
            os.environ["DATABASE_URL_TEST"].replace("postgresql+psycopg:", "postgresql:"), row_factory=dict_row
        ) as conn:
            assert await compute_incident(conn, incident[0]) is not None

    asyncio.run(materialize_fixture())
    params = {"product_line": line, "period": "quarter", "run_id": "current"}
    headers = {"X-Cx-Role": "product_manager", "X-Cx-Product-Line": line}
    before = client.get("/api/cabinet/overview", params=params, headers=headers).json()
    assert before["kpi"]["incidents"] >= 1
    assert before["kpi"]["economics_known"] >= 1
    listed = client.get("/api/cabinet/signals", params={**params, "limit": 200}, headers=headers).json()
    assert sid in {item["id"] for item in listed["items"]}
    try:
        sql.execute("update signals set origin='proactive',channel_code='proactive',client_id=null where id=%s", (sid,))
        stable = fingerprint(sql)
        after = client.get("/api/cabinet/overview", params=params, headers=headers).json()
        rows = client.get("/api/cabinet/signals", params={**params, "limit": 200}, headers=headers).json()
        assert after["kpi"]["signals"] == before["kpi"]["signals"] - 1
        assert rows["total"] == listed["total"] - 1
        assert sid not in {item["id"] for item in rows["items"]}
        assert sql.execute("select count(*) from v_cabinet_signal_facts where id=%s", (sid,)).fetchone()[0] == 0
        for key in ("incidents", "economics_known", "potential_loss_rub", "prevented_loss_rub"):
            assert after["kpi"][key] == before["kpi"][key], key
        assert client.get(f"/api/trace/signal/{sid}", params={"run_id": "current"}).status_code == 200
        assert sql.execute("select count(*) from signals where id=%s", (sid,)).fetchone()[0] == 1
        assert fingerprint(sql) == stable
    finally:
        if not linked:
            sql.execute("delete from incident_signals where incident_id=%s and signal_id=%s", (incident[0], sid))
        sql.execute(
            "update signals set origin=%s,client_id=%s,channel_code=%s where id=%s", (origin, customer, channel, sid)
        )
