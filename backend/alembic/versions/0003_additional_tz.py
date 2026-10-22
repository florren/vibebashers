"""Дополнительное ТЗ v1.4: приёмный слой (transcripts, ingest_sources, ingest_messages, signals.geo/sentiment),
эскалации и тикетница (escalations, v_tickets), семейство conduct, service_scripts, пакетные сессии, зоны карты (v_map_zones)
(исполняет contracts/db/migrations/0003_additional_tz.sql — идемпотентный SQL)

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-21
"""
from __future__ import annotations

from pathlib import Path

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

_HERE = Path(__file__).resolve()
_CANDIDATES = [
    _HERE.parents[2] / "migrations" / "0003_additional_tz.sql",
    _HERE.parents[3] / "contracts" / "db" / "migrations" / "0003_additional_tz.sql",
    Path("/app/migrations/0003_additional_tz.sql"),
]
SQL_FILE = next((p for p in _CANDIDATES if p.exists()), _CANDIDATES[0])

_DROP_OBJECTS = ["VIEW v_map_zones", "VIEW v_tickets", "TABLE service_scripts", "TABLE escalations",
                 "TABLE ingest_messages", "TABLE transcripts", "TABLE ingest_sources"]
_DROP_COLUMNS = [
    ("signals", "sentiment"), ("signals", "transcript_id"), ("signals", "geo"),
    ("incidents", "problem_summary"), ("incidents", "routing_status"),
    ("misselling_patterns", "training_module"), ("misselling_patterns", "recommendation_ru"),
    ("misselling_patterns", "immediate_threshold"), ("misselling_patterns", "alert_policy"), ("misselling_patterns", "family"),
    ("compliance_triggers", "fact_check"), ("compliance_triggers", "recommendation_ru"),
    ("compliance_alerts", "transcript_id"), ("compliance_alerts", "kind"), ("compliance_alerts", "recommendation_ru"),
    ("audio_sessions", "report"), ("audio_sessions", "transcript_id"), ("audio_sessions", "pacing"),
    ("economics_settings", "map_zone_thresholds"),
]
_RESTORE_CHECKS = [
    ("signals", "signals_origin_check", "origin IN ('sim','scenario','jury','landing','telegram_bot','proactive','twin','review_portal','voice_input','api')"),
    ("compliance_alerts", "compliance_alerts_decision_check", "decision IN ('go','false_positive','open_incident')"),
]


def upgrade() -> None:
    op.get_bind().exec_driver_sql(SQL_FILE.read_text(encoding="utf-8"))


def downgrade() -> None:
    for fk in ["signals DROP CONSTRAINT IF EXISTS signals_transcript_fk",
               "audio_sessions DROP CONSTRAINT IF EXISTS audio_sessions_transcript_fk",
               "compliance_alerts DROP CONSTRAINT IF EXISTS compliance_alerts_transcript_fk"]:
        op.execute(f"ALTER TABLE {fk}")
    for obj in _DROP_OBJECTS:
        op.execute(f"DROP {obj} CASCADE")
    for table, col in _DROP_COLUMNS:
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {col}")
    for table, name, expr in _RESTORE_CHECKS:
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}")
        op.execute(f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({expr})")
