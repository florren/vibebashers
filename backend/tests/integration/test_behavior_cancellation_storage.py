"""T039 B: additive0019, реальный PG16 constraint и сохранение unknown legacy."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import psycopg
import pytest
from psycopg.types.json import Jsonb

from app.sim.behavior.cancellation_details import CancellationDetails
from tests.helpers import dsn

ROOT = Path(__file__).resolve().parents[3]
DDL = (ROOT / "contracts/db/migrations/0019_behavior_cancellation_receipts.sql").read_text()
NOW = dt.datetime(2026, 11, 2, 9, tzinfo=dt.UTC)


def payload():
    return CancellationDetails(
        1,
        "complaint",
        NOW + dt.timedelta(hours=1),
        NOW,
        NOW + dt.timedelta(minutes=15),
        None,
        True,
        2,
        "resolution",
        3,
        None,
        NOW - dt.timedelta(minutes=1),
    ).to_json()


@pytest.mark.parametrize(
    "patch",
    [
        {"version": True},
        {"version": 2},
        {"episode_no": True},
        {"episode_no": 0},
        {"episode_no": 1.0},
        {"episode_no": 2**31},
        {"evidence_id": 2**63},
        {"evidence_source_id": False},
        {"canonical_signal_id": True},
        {"canonical_signal_id": 1.5},
        {"work_kind": "gift"},
        {"evidence_kind": "notification"},
        {"complaint_observation_complete": 1},
        {"due_sim": "2026-02-30T09:00:00Z"},
        {"due_sim": "2026-11-02T09:00:00"},
        {"cancellation_observed_sim": "2026-11-02T08:59:00Z"},
        {"resolution_sim": "2026-11-02T09:00:01Z"},
        {"extra": "unsupported"},
    ],
)
def test_pg_shape_matches_strict_codec(migrated_db, patch):
    with psycopg.connect(dsn(migrated_db)) as conn:
        assert conn.execute(
            "select valid_behavior_cancellation_details(%s,%s,%s,%s)",
            ("work", "cancelled_by_resolution", NOW, Jsonb(payload())),
        ).fetchone() == (True,)
        assert conn.execute(
            "select valid_behavior_cancellation_details(%s,%s,%s,%s)",
            ("work", "cancelled_by_resolution", NOW, Jsonb(payload() | patch)),
        ).fetchone() == (False,)


def test_ddl_is_idempotent_and_preserves_old_null_row(seeded):
    with psycopg.connect(dsn(seeded)) as conn:
        run = conn.execute("select id from sim_runs where kind='baseline' order by id limit 1").fetchone()[0]
        client = conn.execute("select id from clients order by id limit 1").fetchone()[0]
        conn.execute(
            "insert into behavior_receipts(run_id,client_id,source_kind,source_id,action,consumed_sim) values(%s,%s,'legacy_schema_probe',1,'keep',%s)",
            (run, client, NOW),
        )
        before = conn.execute(
            "select to_jsonb(r)-'details' from behavior_receipts r where source_kind='legacy_schema_probe'"
        ).fetchone()[0]
        conn.execute(DDL)
        conn.execute(DDL)
        after = conn.execute(
            "select to_jsonb(r)-'details',details from behavior_receipts r where source_kind='legacy_schema_probe'"
        ).fetchone()
        assert after == (before, None)
        column = conn.execute(
            "select is_nullable,column_default from information_schema.columns where table_schema='public' and table_name='behavior_receipts' and column_name='details'"
        ).fetchone()
        assert column == ("YES", None)
        count = conn.execute("select count(*) from behavior_receipts").fetchone()[0]
        with pytest.raises(psycopg.errors.CheckViolation):
            with conn.transaction():
                conn.execute(
                    "insert into behavior_receipts(run_id,client_id,source_kind,source_id,action,consumed_sim,details) values(%s,%s,'work',999,'cancelled_by_resolution',%s,%s)",
                    (run, client, NOW, Jsonb(payload() | {"evidence_id": True})),
                )
        assert conn.execute("select count(*) from behavior_receipts").fetchone()[0] == count


def test_reason_and_logical_receipt_time_are_verified(migrated_db):
    with psycopg.connect(dsn(migrated_db)) as conn:
        for source, action, at in [
            ("notification", "cancelled_by_resolution", NOW),
            (None, "cancelled_by_resolution", NOW),
            ("work", None, NOW),
            ("work", "already_complained", NOW),
            ("work", "cancelled_by_resolution", NOW + dt.timedelta(seconds=1)),
        ]:
            assert conn.execute(
                "select valid_behavior_cancellation_details(%s,%s,%s,%s)", (source, action, at, Jsonb(payload()))
            ).fetchone() == (False,)
        already = payload() | {
            "evidence_kind": "agent_state",
            "canonical_signal_id": 4,
            "first_complaint_sim_at_cancellation": NOW.isoformat(),
            "resolution_sim": None,
        }
        assert conn.execute(
            "select valid_behavior_cancellation_details(%s,%s,%s,%s)",
            ("work", "already_complained", NOW, Jsonb(already)),
        ).fetchone() == (True,)
        assert conn.execute(
            "select valid_behavior_cancellation_details(%s,%s,%s,NULL)", ("legacy", "keep", NOW)
        ).fetchone() == (True,)
