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
    seeded = _seed(migrated_db)
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
    original = sql.execute("select id,run_id from signals order by id desc limit 1").fetchone()
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
