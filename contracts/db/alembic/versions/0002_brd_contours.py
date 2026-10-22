"""Контуры BRD демо-стенда v1.3: Mock-АБС, бизнес-правила, внешние площадки, аудиомониторинг, кассеты replay
(исполняет contracts/db/migrations/0002_brd_contours.sql — идемпотентный SQL)

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-21
"""
from __future__ import annotations

from pathlib import Path

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

_HERE = Path(__file__).resolve()
_CANDIDATES = [
    _HERE.parents[2] / "migrations" / "0002_brd_contours.sql",                       # backend/migrations (копия, make sync-contracts)
    _HERE.parents[3] / "contracts" / "db" / "migrations" / "0002_brd_contours.sql",   # исходник в репозитории
    Path("/app/migrations/0002_brd_contours.sql"),
]
SQL_FILE = next((p for p in _CANDIDATES if p.exists()), _CANDIDATES[0])

# Откат: удаляются только объекты v1.3; колонки и CHECK возвращаются к v1.2.
_DROP_OBJECTS = [
    "VIEW v_compliance_by_employee", "VIEW v_feed_latency",
    "TABLE demo_assets", "TABLE llm_cassettes", "TABLE stt_metrics", "TABLE compliance_alerts", "TABLE compliance_triggers",
    "TABLE utterances", "TABLE audio_sessions", "TABLE misselling_patterns", "TABLE employees", "TABLE branches",
    "TABLE external_replies", "TABLE external_posts", "TABLE rule_evaluations", "TABLE business_rules",
    "TABLE ledger_entries", "TABLE tariffs", "TABLE accounts",
]
_DROP_COLUMNS = [
    ("signals", "external_post_id"), ("signals", "voice_meta"),
    ("operations", "fee_amount"), ("operations", "merchant"), ("operations", "method"),
    ("client_products", "card_last4"), ("clients", "refunds_30d"), ("clients", "social_handles"),
    ("economics_settings", "misselling_case_cost_rub"), ("incident_economics", "refund_amount_rub"),
]
_RESTORE_CHECKS = [
    ("sim_runs", "sim_runs_kind_check", "kind IN ('baseline','free','scenario')"),
    ("incidents", "incidents_incident_type_check", "incident_type IN ('tech_fault','client_error','tariff_terms','service_quality','fraud_suspicion','legal_regulatory','info_request','suggestion','account_closure','proactive')"),
    ("incidents", "incidents_complexity_check", "complexity IN ('easy','medium','hard')"),
    ("incidents", "incidents_created_by_check", "created_by IN ('agent','human','team','behavior_model','scenario')"),
    ("signals", "signals_origin_check", "origin IN ('sim','scenario','jury','landing','telegram_bot','proactive','twin')"),
    ("agent_runs", "agent_runs_kind_check", "kind IN ('agent','client_twin','team_emulator','bench','compare')"),
]


def upgrade() -> None:
    op.execute(SQL_FILE.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("ALTER TABLE signals DROP CONSTRAINT IF EXISTS signals_external_post_fk")
    op.execute("ALTER TABLE audio_sessions DROP CONSTRAINT IF EXISTS audio_sessions_demo_asset_fk")
    for obj in _DROP_OBJECTS:
        op.execute(f"DROP {obj} CASCADE")
    for table, col in _DROP_COLUMNS:
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {col}")
    for table, name, expr in _RESTORE_CHECKS:
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}")
        op.execute(f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({expr})")
