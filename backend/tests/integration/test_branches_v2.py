from __future__ import annotations

import random
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.main import create_app

ROOT = Path(__file__).resolve().parents[3]


def test_seed_branch_network_and_idempotency(
    seeded: str, conn: psycopg.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3]))
    from scripts.seed.refs import seed_branches

    assert conn.execute("select count(*),count(*) filter(where branch_status='closed') from branches").fetchone() == (
        240,
        19,
    )
    assert conn.execute("select count(distinct region_code) from branches").fetchone()[0] == 89
    assert conn.execute("select count(*) from employees").fetchone()[0] == 1440
    assert (
        conn.execute(
            "select count(*) from employees where education is null or hired_sim is null or position_since_sim is null"
        ).fetchone()[0]
        == 0
    )
    original = conn.execute(
        "select code,lat,lon,opened_sim,closed_sim,product_line_codes from branches order by code"
    ).fetchall()
    with conn.cursor() as cur:
        seed_branches(cur, random.Random(42), seed=42)
    assert (
        conn.execute(
            "select code,lat,lon,opened_sim,closed_sim,product_line_codes from branches order by code"
        ).fetchall()
        == original
    )
    assert conn.execute("select count(*) from employees").fetchone()[0] == 1440
    assert conn.execute("select count(*) from branch_network_history").fetchone()[0] == 89 * 12
    assert (
        conn.execute(
            "select display_name from employees e join branches b on b.id=e.branch_id where b.code='0042' and desk_no=3"
        ).fetchone()[0]
        == "Петров П. П."
    )
    assert (
        conn.execute(
            "select display_name from employees e join branches b on b.id=e.branch_id where b.code='0042' and desk_no=5"
        ).fetchone()[0]
        == "Сидорова А. А."
    )
    assert conn.execute("select count(*) from regions where okato is not null").fetchone()[0] == 85


def test_branch_api_pagination_filter_and_ttl(seeded: str) -> None:
    with TestClient(create_app()) as client:
        first = client.get("/api/branches", params={"limit": 200})
        assert first.status_code == 200, first.text
        assert first.headers["cache-control"] == "private, max-age=86400"
        body = first.json()
        assert len(body["items"]) == 200
        second = client.get("/api/branches", params={"limit": 200, "cursor": body["next_cursor"]}).json()
        assert len(second["items"]) == 40
        assert second["next_cursor"] is None
        assert not {b["code"] for b in body["items"]} & {b["code"] for b in second["items"]}
        assert all("manager_chat_id" not in b for b in body["items"])
        closed = client.get("/api/branches", params={"status": "closed"}).json()["items"]
        assert len(closed) == 19 and all(b["branch_status"] == "closed" for b in closed)
        region = client.get("/api/branches", params={"region_code": "63"}).json()["items"]
        assert region and all(b["region_code"] == "63" for b in region)
        history = client.get("/api/branches/network").json()["items"]
        assert len(history) == 12
        assert history[-1]["open_count"] == 221 and history[-1]["closed_count"] == 19
        assert client.get("/api/branches/network?months=0").status_code == 422
        assert client.get("/api/branches?limit=201").status_code == 422
        assert client.get("/api/branches?status=unknown").status_code == 422


def test_seed_default_uses_sim_state_seed(seeded: str, conn: psycopg.Connection) -> None:
    import os
    import subprocess
    import sys

    from app.sim.branch_directory import SyntheticBranchDirectory

    conn.execute("update sim_state set seed=77 where id=1")
    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parents[3] / "scripts/seed/run.py"), "--refs-only"],
        env={**os.environ, "DATABASE_URL": seeded},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    sim_time = conn.execute("select sim_time from sim_state where id=1").fetchone()[0]
    expected = next(b for b in SyntheticBranchDirectory().load(77, sim_time) if b.code == "S0010")
    actual = conn.execute("select lat,lon from branches where code='S0010'").fetchone()
    assert tuple(map(float, actual)) == (expected.lat, expected.lon)
    assert conn.execute("select seed from sim_state where id=1").fetchone()[0] == 77


def test_snapshot_keeps_historical_rows_and_marks_closed(
    seeded: str, conn: psycopg.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3]))
    from scripts.seed.refs import seed_branches

    from app.sim.branch_directory import DATA

    with conn.cursor() as cur:
        seed_branches(cur, random.Random(42), mode="snapshot_file", snapshot=DATA / "import/branches/example.json")
    assert conn.execute("select count(*) from branches").fetchone()[0] == 240
    assert conn.execute("select count(*) from branches where branch_status='open'").fetchone()[0] == 12
    assert (
        conn.execute("select count(*) from branches where branch_status='closed' and closed_sim is null").fetchone()[0]
        == 0
    )
    with TestClient(create_app()) as client:
        data = client.get("/api/branches/network").json()
        assert data["synthetic"] is False
        assert data["items"][-1]["open_count"] == 12
        assert data["items"][-1]["closed_count"] == 228
