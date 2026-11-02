"""T-051: credential configuration и snapshot на AgentRun."""
from pathlib import Path
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql(
        (Path(__file__).resolve().parents[2] / "migrations" / "0013_runtime_profiles.sql").read_text()
    )


def downgrade() -> None:
    # Аддитивная миграция: старое приложение не должно терять encrypted configuration.
    pass
