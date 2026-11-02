"""T-256: native p95 на demo5000, первый GET включён, без warmup/ANALYZE/tracer."""

from __future__ import annotations

import json
import math
import time

import psycopg
import pytest
from fastapi.testclient import TestClient

from tests.integration.conftest import _seed, rebuild_schema
from tests.integration.test_cabinet_api import fingerprint


@pytest.fixture(scope="module")
def demo_db(migrated_db):
    rebuild_schema(migrated_db)
    result = _seed(migrated_db, "--profile", "demo", "--clients", "5000")
    assert result.returncode == 0, result.stderr[-1000:]
    with psycopg.connect(migrated_db.replace("postgresql+psycopg:", "postgresql:")) as conn:
        assert conn.execute("SELECT count(*) FROM clients").fetchone()[0] == 5000
    return migrated_db


def test_demo_cx_and_overview_native_p95_first_get_included(demo_db, monkeypatch, record_property):
    from app.main import create_app

    def bomb(*args, **kwargs):
        raise AssertionError("Metrics reader must not invoke external/monetary producer")

    monkeypatch.setattr("app.economics.dcltv.compute_incident", bomb)
    monkeypatch.setattr("app.economics.dcltv.recompute", bomb)
    monkeypatch.setattr("app.llm.failover.ProviderChain.complete_structured", bomb)
    proof = {}
    with (
        TestClient(create_app()) as client,
        psycopg.connect(demo_db.replace("postgresql+psycopg:", "postgresql:"), autocommit=True) as sql,
    ):
        before = fingerprint(sql)
        for endpoint in ("cx-index", "overview"):
            samples = []
            for _ in range(30):
                started = time.perf_counter()
                response = client.get("/api/metrics/" + endpoint, params={"run_id": "all"})
                elapsed = (time.perf_counter() - started) * 1000
                assert response.status_code == 200, response.text[:300]
                samples.append(elapsed)
            p95 = sorted(samples)[math.ceil(0.95 * len(samples)) - 1]
            proof[endpoint] = {"p95_ms": p95, "samples_ms": samples, "clients": 5000, "first_get_included": True}
            record_property(endpoint, json.dumps(proof[endpoint]))
            assert p95 < 300, json.dumps(proof[endpoint])
        assert fingerprint(sql) == before
