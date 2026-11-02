"""T-241: read-only кабинет и nullable provenance человеческих действий."""

from pathlib import Path

from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql(
        (
            Path(__file__).resolve().parents[2]
            / "migrations"
            / "0018_cabinet_scope.sql"
        ).read_text()
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS v_cabinet_incident_facts")
    op.execute("DROP VIEW IF EXISTS v_cabinet_signal_facts")
    op.execute("DROP INDEX IF EXISTS signals_cabinet_scope_time_idx")
    op.execute("DROP INDEX IF EXISTS product_history_scope_month_idx")
    # Происхождение автора неизменяемого аудита сохраняется при откате кода;
    # старое приложение игнорирует nullable поля. Физический drop — отдельное решение.
