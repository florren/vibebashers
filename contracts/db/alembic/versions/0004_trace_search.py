"""След и поиск v1.5: public_id, pg_trgm, FTS и индексы FK (contracts/db/migrations/0004_trace_search.sql — идемпотентный SQL)

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-27
"""
from __future__ import annotations

from pathlib import Path

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

_HERE = Path(__file__).resolve()
_CANDIDATES = [
    _HERE.parents[2] / "migrations" / "0004_trace_search.sql",
    _HERE.parents[3] / "contracts" / "db" / "migrations" / "0004_trace_search.sql",
    Path("/app/migrations/0004_trace_search.sql"),
]
SQL_FILE = next((p for p in _CANDIDATES if p.exists()), _CANDIDATES[0])

_DROP_INDEXES = [
    "ledger_entries_agent_run_idx",
    "escalations_agent_run_idx",
    "escalations_signal_idx",
    "escalations_incident_idx",
    "human_decisions_agent_run_idx",
    "human_decisions_signal_idx",
    "human_decisions_incident_idx",
    "followups_agent_run_idx",
    "followups_signal_idx",
    "followups_incident_idx",
    "client_reactions_agent_run_idx",
    "client_reactions_notification_idx",
    "external_replies_agent_run_idx",
    "external_replies_incident_idx",
    "tasks_incident_idx",
    "incident_signals_incident_idx",
    "clients_social_handles_trgm_idx",
    "followups_public_id_trgm_idx",
    "human_decisions_public_id_trgm_idx",
    "ledger_entries_public_id_trgm_idx",
    "notifications_public_id_trgm_idx",
    "tasks_public_id_trgm_idx",
    "sim_runs_public_id_trgm_idx",
    "agent_runs_public_id_trgm_idx",
    "external_posts_text_fts_idx",
    "incidents_title_fts_idx",
    "signals_text_fts_idx",
    "followups_public_id_uidx",
    "human_decisions_public_id_uidx",
    "ledger_entries_public_id_uidx",
    "notifications_public_id_uidx",
    "tasks_public_id_uidx",
    "sim_runs_public_id_uidx",
    "agent_runs_public_id_uidx",
]
_DROP_COLUMNS = [
    ("followups", "public_id"),
    ("human_decisions", "public_id"),
    ("ledger_entries", "public_id"),
    ("notifications", "public_id"),
    ("tasks", "public_id"),
    ("sim_runs", "public_id"),
    ("agent_runs", "public_id"),
]


def upgrade() -> None:
    op.get_bind().exec_driver_sql(SQL_FILE.read_text(encoding="utf-8"))


def downgrade() -> None:
    for idx in _DROP_INDEXES:
        op.execute(f"DROP INDEX IF EXISTS {idx}")
    for table, col in _DROP_COLUMNS:
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {col}")
