"""T-017: настоящий COPY, продуктовые ограничения и повторный seed."""

from __future__ import annotations

import datetime as dt
import random
from pathlib import Path

import psycopg
import pytest

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[3]


def test_copy_history_and_products(seeded, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))
    from scripts.seed.operations import seed_operations

    with psycopg.connect(seeded.replace("postgresql+psycopg://", "postgresql://")) as conn, conn.cursor() as cur:
        run_id = cur.execute("select id from sim_runs where kind='baseline' order by id limit 1").fetchone()[0]
        assert (
            cur.execute(
                "select count(*) from (select c.id,count(cp.id) n from clients c left join client_products cp on cp.client_id=c.id group by c.id having count(cp.id) not between 1 and 4) q"
            ).fetchone()[0]
            == 0
        )
        assert (
            cur.execute(
                "select count(*) from client_products where card_last4 is not null and terms->>'masked_number' is distinct from '**** '||card_last4"
            ).fetchone()[0]
            == 0
        )
        assert (
            cur.execute(
                "select count(*) from client_products where product_code='deposit' and terms->>'promo_code' is not null"
            ).fetchone()[0]
            > 0
        )
        before = cur.execute(
            "select id,client_id,system_path,status,error_code,started_sim,finished_sim from operations where run_id=%s order by id",
            (run_id,),
        ).fetchall()
        assert 4700 <= len(before) <= 4900
        assert (
            cur.execute(
                "select count(*) from operations where run_id=%s and status='failed' and error_code is null", (run_id,)
            ).fetchone()[0]
            == 0
        )
        assert (
            cur.execute(
                "select count(*) from operations o cross join unnest(o.system_path) s where not exists(select 1 from systems where code=s)"
            ).fetchone()[0]
            == 0
        )
        seed_operations(cur, random.Random(99), run_id, dt.datetime(2026, 11, 9, 9, tzinfo=dt.UTC))
        assert (
            cur.execute(
                "select id,client_id,system_path,status,error_code,started_sim,finished_sim from operations where run_id=%s order by id",
                (run_id,),
            ).fetchall()
            == before
        )

        # Exercise the actual COPY in this process, not only the seed subprocess.
        cur.execute("delete from operations where run_id=%s", (run_id,))
        seed_operations(cur, random.Random(42), run_id, dt.datetime(2026, 11, 9, 9, tzinfo=dt.UTC), per_client=5)
        assert cur.execute("select count(*) from operations where run_id=%s", (run_id,)).fetchone()[0] == 1000
        assert (
            cur.execute("select count(*) from operations where status='failed' and error_code is null").fetchone()[0]
            == 0
        )

        # Exercise min-product fallback and masked terms in-process as well as via CLI.
        from scripts.seed.clients import seed_clients

        seed_clients(cur, random.Random(42), 1000, dt.datetime(2026, 11, 9, 9, tzinfo=dt.UTC))
        assert cur.execute("select count(*) from clients").fetchone()[0] == 1000
        assert (
            cur.execute(
                "select count(*) from (select c.id from clients c left join client_products cp on cp.client_id=c.id group by c.id having count(cp.id) not between 1 and 4) q"
            ).fetchone()[0]
            == 0
        )
