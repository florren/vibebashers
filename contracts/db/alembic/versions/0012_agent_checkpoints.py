"""T-041: персистентные checkpoint LangGraph с изоляцией запусков."""
from pathlib import Path
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql(
        (Path(__file__).resolve().parents[2] / "migrations" / "0012_agent_checkpoints.sql").read_text()
    )


def downgrade() -> None:
    # Аддитивная миграция: откат приложения сохраняет checkpoints.
    pass
