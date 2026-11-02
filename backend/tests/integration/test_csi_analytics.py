"""T-248: native import → actual GET, scoped probability и read-only доказательство."""

import asyncio
from pathlib import Path

import psycopg
import pytest
import yaml
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.ingest.csi_cohorts import install_scoped_sample
from app.main import create_app
from tests.helpers import dsn
from tests.integration.test_cabinet_api import fingerprint
from tests.integration.test_csi_cohort_install import sample_run

ROOT = Path(__file__).resolve().parents[3]


def install(url):
    async def run():
        async with await psycopg.AsyncConnection.connect(dsn(url), row_factory=dict_row) as conn:
            run_id = await sample_run(conn)
            await install_scoped_sample(conn)
            await conn.commit()
            return run_id

    return asyncio.run(run())


def get(client, **params):
    response = client.get("/api/csi/analytics", params=params)
    assert response.status_code == 200, response.text
    data = response.json()
    contract = yaml.safe_load((ROOT / "contracts/api/openapi.yaml").read_text())
    Draft202012Validator(
        {"$ref": "#/components/schemas/CsiAnalyticsResponse", "components": contract["components"]}
    ).validate(data)
    return data


def test_complete_native_sample_schema_bounds_and_read_only(seeded):
    run_id = install(seeded)
    with psycopg.connect(dsn(seeded), autocommit=True) as sql, TestClient(create_app()) as client:
        before = fingerprint(sql)
        result = get(client, limit=17, scatter_limit=19)
        assert result["scope"]["run_ids"][-1] == run_id
        assert result["coverage"]["complaints"] == result["coverage"]["cohort_bound"] == 300
        assert result["coverage"]["uncohorted"] == 0
        assert len(result["complaints"]["items"]) == 17 and result["complaints"]["next_offset"] == 17
        assert result["scatter"]["shown"] == 19 and result["scatter"]["has_more"]
        assert result["scatter"]["total"] == 300
        p = result["probabilities"]
        assert (p["complete_cohorts"], p["sample_complaints"], p["sample_visits"]) == (10, 300, 2400)
        assert p["synthetic"] is True and p["mixed_sources"] is False
        assert p["legacy_denominators_usable"] is False
        for axis, n in [("wait", 4), ("redirects", 3)]:
            assert p[axis]["n_buckets"] == n
            assert p[axis]["spearman"] == pytest.approx(1)
            assert sum(x["visits"] for x in p[axis]["buckets"]) == 2400
            assert sum(x["complaints"] for x in p[axis]["buckets"]) == 300
        assert (
            sum(x["employees"] for x in result["tenure"]["groups"])
            == sql.execute("select count(*) from employees where is_active").fetchone()[0]
        )
        assert all(x["q1"] <= x["median"] <= x["q3"] for x in result["tenure"]["groups"] if x["known_tenure"])
        assert len(get(client, offset=299)["complaints"]["items"]) == 1
        assert get(client, offset=300)["complaints"]["items"] == []
        assert fingerprint(sql) == before


def test_strict_direction_filters_numerator_and_denominator_together(seeded):
    install(seeded)
    with psycopg.connect(dsn(seeded), autocommit=True) as sql, TestClient(create_app()) as client:
        sql.execute(
            "insert into settings(key,value) values('cabinet',%s) on conflict(key) do update set value=excluded.value",
            (Jsonb({"visibility": "strict"}),),
        )
        line = sql.execute("select product_line_code from csi_cohorts order by id limit 1").fetchone()[0]
        expected = sql.execute(
            "select sum(member_count),sum(sample_visits) from v_csi_cohort_integrity where product_line_code=%s",
            (line,),
        ).fetchone()
        headers = {"X-Cx-Role": "product_manager", "X-Cx-Product-Line": line}
        response = client.get("/api/csi/analytics", headers=headers)
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["coverage"]["complaints"] == expected[0]
        assert result["probabilities"]["sample_visits"] == expected[1]
        assert all(x["product_line_code"] == line for x in result["complaints"]["items"])
        foreign = sql.execute("select code from product_lines where code<>%s limit 1", (line,)).fetchone()[0]
        assert client.get("/api/csi/analytics", params={"product_line": foreign}, headers=headers).status_code == 403
        assert client.get("/api/csi/analytics", params={"product_line": "all"}, headers=headers).status_code == 403


def test_deleted_cohort_member_is_unknown_not_fabricated_zero(seeded):
    install(seeded)
    with psycopg.connect(dsn(seeded), autocommit=True) as sql, TestClient(create_app()) as client:
        branch = sql.execute("select branch_id from csi_cohorts order by id limit 1").fetchone()[0]
        sql.execute(
            "delete from csi_cohort_members where signal_id=(select min(signal_id) from csi_cohort_members where branch_id=%s)",
            (branch,),
        )
        p = get(client, branch_id=branch)["probabilities"]
        assert p["incomplete_cohorts"] == 1 and p["complete_cohorts"] == 0
        assert p["sample_visits"] is None and p["sample_complaints"] is None
        assert all(x["probability"] is None for x in p["wait"]["buckets"])


def test_current_does_not_fall_back_to_all_and_explicit_history_is_available(seeded):
    old_run = install(seeded)

    async def new():
        async with await psycopg.AsyncConnection.connect(dsn(seeded), row_factory=dict_row) as conn:
            await sample_run(conn)
            await conn.commit()

    asyncio.run(new())
    with TestClient(create_app()) as client:
        empty = get(client)
        assert empty["coverage"]["complaints"] == 0
        assert empty["probabilities"]["sample_visits"] is None
        assert get(client, run_id=old_run)["coverage"]["complaints"] == 300
        assert get(client, run_id="all")["probabilities"]["sample_visits"] == 2400


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 201},
        {"scatter_limit": 5001},
        {"offset": -1},
        {"branch_id": 0},
        {"branch_id": 2147483648},
        {"run_id": "bad"},
        {"period": "year"},
    ],
)
def test_invalid_bounds_rejected_before_db(params):
    with TestClient(create_app()) as client:
        assert client.get("/api/csi/analytics", params=params).status_code == 422
