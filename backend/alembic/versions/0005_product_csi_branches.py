"""Кабинет, CSI и ВСП v1.5 (contracts/db/migrations/0005_product_csi_branches.sql — идемпотентный SQL)

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-27
"""
from __future__ import annotations

from pathlib import Path

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

_HERE = Path(__file__).resolve()
_CANDIDATES = [
    _HERE.parents[2] / "migrations" / "0005_product_csi_branches.sql",
    _HERE.parents[3] / "contracts" / "db" / "migrations" / "0005_product_csi_branches.sql",
    Path("/app/migrations/0005_product_csi_branches.sql"),
]
SQL_FILE = next((p for p in _CANDIDATES if p.exists()), _CANDIDATES[0])

_NEW_TABLES = (
    "branch_network_history",
    "csi_visits_agg",
    "csi_responses",
    "product_signal_history",
    "product_lines",
)
_VIEWS = ("v_cabinet_kpi", "v_signal_normalized")
_SIGNAL_COLS = ("meta", "flags", "red_words", "product_line_code")
_BRANCH_COLS = (
    "product_line_codes",
    "closed_sim",
    "opened_sim",
    "hours_ru",
    "address_ru",
    "lon",
    "lat",
    "branch_status",
    "branch_type",
)
_EMP_COLS = ("position_since_sim", "education")


def upgrade() -> None:
    op.get_bind().exec_driver_sql(SQL_FILE.read_text(encoding="utf-8"))


def downgrade() -> None:
    for v in _VIEWS:
        op.execute(f"DROP VIEW IF EXISTS {v}")
    for t in _NEW_TABLES:
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    # Канал остаётся справочным значением: удаление нарушит FK существующих сигналов,
    # уведомлений и шаблонов. Схема v1.4 допускает произвольные коды каналов.
    for col in _SIGNAL_COLS:
        op.execute(f"ALTER TABLE signals DROP COLUMN IF EXISTS {col}")
    op.execute("ALTER TABLE regions DROP COLUMN IF EXISTS okato")
    for col in _BRANCH_COLS:
        op.execute(f"ALTER TABLE branches DROP COLUMN IF EXISTS {col}")
    for col in _EMP_COLS:
        op.execute(f"ALTER TABLE employees DROP COLUMN IF EXISTS {col}")
    op.execute("DROP INDEX IF EXISTS signals_flags_gin_idx")
    op.execute("DROP INDEX IF EXISTS signals_product_line_idx")
