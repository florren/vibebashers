"""Начальная схема CX Pulse Control (исполняет contracts/db/schema.sql)

Revision ID: 0001
Revises:
Create Date: 2026-10-21
"""
from __future__ import annotations

from pathlib import Path

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

# Поиск schema.sql: сначала рядом с каталогом alembic (backend/schema.sql — копия, обновляемая make sync-contracts),
# затем исходник в contracts/db/schema.sql в корне репозитория.
_HERE = Path(__file__).resolve()
_CANDIDATES = [
    _HERE.parents[2] / "schema.sql",
    _HERE.parents[3] / "contracts" / "db" / "schema.sql",
    Path("/app/schema.sql"),
]
SCHEMA_FILE = next((p for p in _CANDIDATES if p.exists()), _CANDIDATES[0])

# Порядок удаления при откате — обратный созданию; представления и функции удаляются первыми.
_DROP_ORDER = [
    "VIEW v_run_counters", "VIEW v_region_heat", "VIEW v_retention_by_outcome", "VIEW v_incident_outcomes", "VIEW v_faults_by_product_hour",
    "TABLE bench_results", "TABLE bench_runs", "TABLE bench_cases", "TABLE bench_datasets",
    "TABLE scenarios", "TABLE sim_events", "TABLE sim_state",
    "TABLE followups", "TABLE human_decisions", "TABLE agent_steps",
    "TABLE churn_events", "TABLE client_reactions", "TABLE client_states",
    "TABLE incident_economics", "TABLE notifications", "TABLE tasks", "TABLE team_actions",
    "TABLE incident_artifacts", "TABLE incident_status_history", "TABLE incident_signals",
    "TABLE incidents", "TABLE agent_runs", "TABLE signals", "TABLE system_logs", "TABLE faults", "TABLE operations",
    "TABLE client_products", "TABLE clients",
    "TABLE gift_catalog", "TABLE economics_settings", "TABLE dcltv_rates", "TABLE settings", "TABLE llm_api_keys",
    "TABLE llm_profiles", "TABLE routing_rules", "TABLE sla_matrix", "TABLE notification_templates", "TABLE signal_types",
    "TABLE error_codes", "TABLE channels", "TABLE team_systems", "TABLE teams", "TABLE systems", "TABLE products",
    "TABLE segment_psychotype_mix", "TABLE psychotypes", "TABLE segments", "TABLE cities", "TABLE regions",
    "TABLE federal_districts", "TABLE sim_runs", "TABLE db_activity_log",
    "FUNCTION log_db_activity()", "FUNCTION set_updated_at()",
]


def upgrade() -> None:
    sql = SCHEMA_FILE.read_text(encoding="utf-8")
    op.get_bind().exec_driver_sql(sql)  # exec_driver_sql: без разбора :параметров внутри DDL и $$-тел функций


def downgrade() -> None:
    for obj in _DROP_ORDER:
        op.execute(f"DROP {obj} CASCADE")
