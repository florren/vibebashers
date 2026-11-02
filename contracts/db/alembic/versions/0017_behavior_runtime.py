"""T-161: долговечные состояния, evidence, receipts и таймеры behavior."""
from pathlib import Path
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql(
        (Path(__file__).resolve().parents[2] / "migrations" / "0017_behavior_runtime.sql").read_text()
    )


def downgrade() -> None:
    # Forward-only: историю состояний/receipts нельзя уничтожать при rollback кода.
    pass
