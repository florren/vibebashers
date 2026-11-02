"""T-039 B: nullable versioned cancellation provenance, без изменения модели/денег."""

from pathlib import Path

from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql(
        (Path(__file__).resolve().parents[2] / "migrations" / "0019_behavior_cancellation_receipts.sql").read_text()
    )


def downgrade() -> None:
    # Provenance не удаляется при откате приложения; старый код допускает NULL.
    # Физическое удаление audit column требует отдельного решения.
    return
