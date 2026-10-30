"""T-267: журнал информации оператора HITL."""
from pathlib import Path
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql((Path(__file__).resolve().parents[2] / "migrations" / "0009_hitl_feedback.sql").read_text())


def downgrade() -> None:
    # История сохраняется при откате приложения.
    pass
