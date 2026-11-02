"""T-248: native demo5000, первые GET включены, threshold300 и actual EXPLAIN."""

import hashlib
import json
import math
import time
from pathlib import Path

import psycopg
from fastapi.testclient import TestClient

from app.analytics import branches, csi
from app.main import create_app
from tests.helpers import dsn
from tests.integration.conftest import _seed, rebuild_schema
from tests.integration.test_cabinet_api import fingerprint
from tests.integration.test_csi_analytics import install

ROOT = Path(__file__).resolve().parents[3]


def test_demo_csi_branch_gets_p95_and_actual_plans(migrated_db, monkeypatch):
    rebuild_schema(migrated_db)
    result = _seed(migrated_db, "--profile", "demo", "--clients", "5000")
    assert result.returncode == 0, result.stderr[-2000:]
    install(migrated_db)
    queries = []
    capture = False

    def wrap(function):
        async def observed(conn, sql, args=()):
            if capture:
                queries.append((sql, args))
            return await function(conn, sql, args)

        return observed

    for module in [csi, branches]:
        for name in ["fetch_one", "fetch_all"]:
            monkeypatch.setattr(module, name, wrap(getattr(module, name)))
    with psycopg.connect(dsn(migrated_db), autocommit=True) as sql, TestClient(create_app()) as client:
        assert sql.execute("select count(*) from clients").fetchone()[0] == 5000
        code = sql.execute(
            "select b.code from csi_cohorts c join branches b on b.id=c.branch_id order by c.id limit 1"
        ).fetchone()[0]
        before = fingerprint(sql)
        evidence = {
            "profile": "demo5000",
            "requests_per_route": 30,
            "first_included": True,
            "warmup": False,
            "threshold_ms": 300,
            "routes": {},
            "source_sha256": {
                str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in [
                    ROOT / "backend/app/analytics/csi.py",
                    ROOT / "backend/app/analytics/branches.py",
                    ROOT / "backend/app/api/branches.py",
                    ROOT / "backend/app/api/csi.py",
                ]
            },
        }
        for route in ["/api/csi/analytics", "/api/branches/analytics", "/api/branches/" + code]:
            samples = []
            for index in range(30):
                capture = index == 0
                start = time.perf_counter()
                response = client.get(route)
                samples.append((time.perf_counter() - start) * 1000)
                assert response.status_code == 200, response.text
            capture = False
            evidence["routes"][route] = {
                "samples_ms": samples,
                "first_ms": samples[0],
                "p95_ms": sorted(samples)[math.ceil(len(samples) * 0.95) - 1],
            }
        plans = []
        seen = set()
        with sql.transaction():
            sql.execute("SET TRANSACTION READ ONLY")
            for query, args in queries:
                key = (query, repr(args))
                if key in seen:
                    continue
                seen.add(key)
                plan = sql.execute("EXPLAIN(ANALYZE,BUFFERS,FORMAT JSON) " + query, args).fetchone()[0][0]
                plans.append({"sql": query, "plan": plan})
        evidence["plans"] = plans
        evidence["fingerprints_unchanged"] = fingerprint(sql) == before
        output = ROOT / "test-results/t248-demo-performance.json"
        output.parent.mkdir(exist_ok=True)
        output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n")
        assert evidence["fingerprints_unchanged"]
        for item in evidence["routes"].values():
            assert item["p95_ms"] < 300, item
