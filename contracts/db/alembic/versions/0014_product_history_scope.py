"""T-240: история направлений с изоляцией запуска и качеством наблюдений."""
from pathlib import Path
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql(
        (Path(__file__).resolve().parents[2] / "migrations" / "0014_product_history_scope.sql").read_text()
    )


def downgrade() -> None:
    # Потеря run_id/quality недопустима: откат приложения сохраняет аддитивную схему.
    pass
