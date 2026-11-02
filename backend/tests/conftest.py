from __future__ import annotations

import os

import pytest

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("LLM_PROVIDER", "mock")


@pytest.fixture
def replay_bank(migrated_db, monkeypatch):
    """Общий неизменный synthetic bank записанной кассеты; это не текущий seed."""
    import datetime as dt
    import json
    import random
    import subprocess
    import sys
    from pathlib import Path

    import psycopg

    from app.contracts.registry import deref
    from app.llm.base import normalize_messages
    from app.replay.store import CassetteStore, request_hash

    root = Path(__file__).resolve().parents[2]
    monkeypatch.syspath_prepend(str(root))
    from scripts.seed.refs import seed_all_refs

    fixture = json.loads((root / "backend/tests/fixtures/replay_bank_v1.json").read_text())
    record = next(
        json.loads(line)
        for line in (root / "data/cassettes/gigachat.jsonl").read_text().splitlines()
        if json.loads(line)["request_hash"] == fixture["source_request_hash"]
    )
    assert normalize_messages(record["messages"]) == record["messages"]
    schema = deref("agent/instant_decision")
    current_hash = request_hash(record["provider"], record["model"], record["messages"], schema)
    # Historical hash остаётся provenance; текущая schema требует настоящий новый ответ.
    current = CassetteStore(root / "data/cassettes").get(
        record["provider"], record["model"], record["messages"], schema
    )
    assert current is not None and current["request_hash"] == current_hash, (
        "recorded bank требует актуальную реально записанную schema; rekey запрещён"
    )
    dsn = migrated_db.replace("postgresql+psycopg://", "postgresql://", 1)
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("drop schema public cascade; create schema public")
    applied = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=root / "backend",
        env={**os.environ, "DATABASE_URL": migrated_db},
        capture_output=True,
        text=True,
    )
    assert applied.returncode == 0, applied.stderr
    now = dt.datetime.fromisoformat(fixture["sim_time"])
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        seed_all_refs(cur, random.Random(42), seed=42, sim_time=now)
        client = fixture["client"]
        city_id = cur.execute(
            "select id from cities where name_ru=%s and region_code=%s", (client["city"], client["region_code"])
        ).fetchone()[0]
        client_id = cur.execute(
            "insert into clients(display_name,segment_code,psychotype_code,region_code,city_id,churn_risk,clv_estimate_rub) values('Клиент replay',%s,%s,%s,%s,%s,100000) returning id",
            (client["segment"], client["psychotype"], client["region_code"], city_id, client["churn_risk"]),
        ).fetchone()[0]
        product = fixture["product"]
        cur.execute(
            "insert into client_products(client_id,product_code,status,card_last4) values(%s,%s,%s,%s)",
            (client_id, product["product"], product["status"], product["card_last4"]),
        )
        cur.execute("insert into sim_state(id,sim_time,seed) values(1,%s,42)", (now,))
        cur.execute("select setval(pg_get_serial_sequence('operations','id'),%s)", (fixture["operation_sequence"],))
    return migrated_db
