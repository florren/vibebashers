"""T-248: directory presets, реальные CSI связи, pressure и closure facts."""

import psycopg
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from app.main import create_app
from tests.helpers import dsn
from tests.integration.test_cabinet_api import assert_schema, fingerprint
from tests.integration.test_csi_analytics import install


def test_branch_detail_pressure_and_gets_do_not_write(seeded):
    install(seeded)
    with psycopg.connect(dsn(seeded), autocommit=True) as sql, TestClient(create_app()) as client:
        code, branch_id = sql.execute(
            "select b.code,b.id from csi_cohorts c join branches b on b.id=c.branch_id order by c.id limit 1"
        ).fetchone()
        before = fingerprint(sql)
        detail = client.get("/api/branches/" + code, params={"limit": 7})
        assert detail.status_code == 200, detail.text
        data = detail.json()
        assert_schema(data, "BranchDetailResponse")
        assert data["branch"]["id"] == branch_id
        assert data["signals"]["total"] == data["csi"]["coverage"]["complaints"] == 29
        assert len(data["signals"]["items"]) == 7 and data["signals"]["next_offset"] == 7
        assert data["trace_path"] == "/trace/branch/" + code
        response = client.get("/api/branches/analytics")
        assert response.status_code == 200, response.text
        result = response.json()
        assert_schema(result, "BranchAnalyticsResponse")
        assert sum(x["signals"] for x in result["pressure"]) == 300
        assert sum(x["branches"] for x in result["pressure"]) == 240
        assert result["deficit_threshold"] is None and all(x["deficit"] is None for x in result["pressure"])
        for row in result["pressure"]:
            assert row["signals_per_open_branch"] == (
                row["signals"] / row["open_branches"] if row["open_branches"] else None
            )
        assert len(result["network"]["items"]) == 12
        assert fingerprint(sql) == before
        assert client.get("/api/branches/not-a-branch").status_code == 404


def test_strict_branch_list_detail_network_and_pressure_share_direction(seeded):
    install(seeded)
    with psycopg.connect(dsn(seeded), autocommit=True) as sql, TestClient(create_app()) as client:
        sql.execute(
            "insert into settings(key,value) values('cabinet',%s) on conflict(key) do update set value=excluded.value",
            (Jsonb({"visibility": "strict"}),),
        )
        line, code = sql.execute(
            "select c.product_line_code,b.code from csi_cohorts c join branches b on b.id=c.branch_id order by c.id limit 1"
        ).fetchone()
        headers = {"X-Cx-Role": "product_manager", "X-Cx-Product-Line": line}
        response = client.get("/api/branches", params={"limit": 200}, headers=headers)
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "private, max-age=86400"
        assert set(response.headers["vary"].split(", ")) == {"X-Cx-Role", "X-Cx-Product-Line", "Origin"}
        assert_schema(response.json(), "BranchDirectoryResponse")
        assert all(line in b["product_line_codes"] for b in response.json()["items"])
        assert client.get("/api/branches/" + code, headers=headers).json()["signals"]["total"] == 29
        foreign = sql.execute(
            "select code from branches where not (%s=ANY(product_line_codes)) limit 1", (line,)
        ).fetchone()[0]
        assert client.get("/api/branches/" + foreign, headers=headers).status_code == 404
        assert client.get("/api/branches?product_line=all", headers=headers).status_code == 403
        history = client.get("/api/branches/network", headers=headers)
        assert history.status_code == 200, history.text
        assert_schema(history.json(), "BranchNetworkResponse")
        assert history.json()["basis"] == "scoped_directory_lifecycle"
        assert len(history.json()["items"]) == 12
        expected = sql.execute(
            "select count(*) filter(where branch_status='open'),count(*) filter(where branch_status='closed') from branches where %s=ANY(product_line_codes)",
            (line,),
        ).fetchone()
        assert (history.json()["items"][-1]["open_count"], history.json()["items"][-1]["closed_count"]) == expected
        pressure = client.get("/api/branches/analytics", headers=headers)
        assert pressure.status_code == 200, pressure.text
        expected_complaints = sql.execute(
            "select sum(member_count) from csi_cohorts where product_line_code=%s", (line,)
        ).fetchone()[0]
        assert sum(x["signals"] for x in pressure.json()["pressure"]) == expected_complaints


def test_closure_same_city_native_window_and_configured_threshold(seeded):
    install(seeded)
    with psycopg.connect(dsn(seeded), autocommit=True) as sql, TestClient(create_app()) as client:
        branch_id = sql.execute("select branch_id from csi_cohorts order by id limit 1").fetchone()[0]
        sql.execute(
            "update branches set branch_status='closed',closed_sim=(select sim_time from sim_state where id=1)-interval '1 day' where id=%s",
            (branch_id,),
        )
        sql.execute(
            "insert into settings(key,value) values('csi_analytics',%s)",
            (Jsonb({"deficit_signals_per_open_branch": 0.00001}),),
        )
        result = client.get("/api/branches/analytics").json()
        own = next(x for x in result["closure_zones"]["items"] if x["branch_id"] == branch_id)
        expected = sql.execute(
            "select count(*) from csi_responses cr join signals s on s.id=cr.signal_id join branches src on src.id=cr.branch_id join branches closed on closed.id=%s where src.city_id=closed.city_id and src.region_code=closed.region_code and s.received_sim>=closed.closed_sim and s.received_sim<closed.closed_sim+interval '90 days' and s.run_id=(select current_run_id from sim_state where id=1)",
            (branch_id,),
        ).fetchone()[0]
        assert own["signals"] == expected and expected == 29
        assert any(x["deficit"] is True for x in result["pressure"])
        beyond = client.get("/api/branches/analytics?offset=100000").json()["closure_zones"]
        assert beyond["items"] == [] and beyond["total"] == result["closure_zones"]["total"]
        # Зона относится ко времени сигнала, а не только к возрасту закрытия
        # на текущих часах. Её 90-дневное окно пересекает week, но уже не day.
        sql.execute(
            "update branches set closed_sim=(select sim_time from sim_state where id=1)-interval '91 days' where id=%s",
            (branch_id,),
        )
        week = client.get("/api/branches/analytics?period=week").json()["closure_zones"]["items"]
        assert next(x for x in week if x["branch_id"] == branch_id)["signals"] == 0
        day = client.get("/api/branches/analytics?period=day").json()["closure_zones"]["items"]
        assert all(x["branch_id"] != branch_id for x in day)
        sql.execute(
            "update settings set value=%s where key='csi_analytics'", (Jsonb({"deficit_signals_per_open_branch": -1}),)
        )
        assert client.get("/api/branches/analytics").status_code == 409


def test_unknown_status_directory_metadata_and_thresholds_remain_explicit(seeded):
    from tests.integration.test_cabinet_api import assert_schema

    install(seeded)
    with psycopg.connect(dsn(seeded), autocommit=True) as sql, TestClient(create_app()) as client:
        branch_id, region = sql.execute(
            "select b.id,b.region_code from csi_cohorts c join branches b on b.id=c.branch_id order by c.id limit 1"
        ).fetchone()
        sql.execute("update branches set branch_status=NULL where id=%s", (branch_id,))
        pressure = client.get("/api/branches/analytics").json()["pressure"]
        row = next(x for x in pressure if x["region_code"] == region)
        assert row["unknown_status_branches"] == 1 and row["signals_per_open_branch"] is None
        for threshold in [True, 0, -1, "many", 10**1000, []]:
            sql.execute(
                "insert into settings(key,value) values('csi_analytics',%s) on conflict(key) do update set value=excluded.value",
                (Jsonb({"deficit_signals_per_open_branch": threshold}),),
            )
            response = client.get("/api/branches/analytics")
            assert response.status_code == 409, (threshold, response.text)
        # Справочник доступен без часов. Unknown source/time не становится
        # synthetic=True, сегодняшней датой или чужой неразмеченной историей.
        line = sql.execute("select product_line_code from csi_cohorts order by id limit 1").fetchone()[0]
        sql.execute(
            "update settings set value=%s where key='branch_directory'",
            (Jsonb({"mode": "unknown", "is_synthetic": 0, "as_of_sim": "bad"}),),
        )
        sql.execute("delete from sim_state where id=1")
        response = client.get("/api/branches")
        assert response.status_code == 200, response.text
        assert_schema(response.json(), "BranchDirectoryResponse")
        assert response.json()["directory"] == {
            "mode": None,
            "synthetic": None,
            "as_of_sim": None,
            "scope": "global_directory_snapshot",
        }
        network = client.get("/api/branches/network", params={"product_line": line})
        assert network.status_code == 200, network.text
        assert network.json()["items"] == [] and network.json()["basis"] == "unavailable_snapshot_time"
        assert client.get("/api/csi/analytics").status_code == 409
