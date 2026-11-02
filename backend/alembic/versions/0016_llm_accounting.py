"""T-050: durable inference admission outside bank baseline."""
from pathlib import Path
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql(
        (Path(__file__).resolve().parents[2] / "migrations" / "0016_llm_accounting.sql").read_text()
    )


def downgrade() -> None:
    # Forward-only: restore/downgrade не возвращает уже потраченные квоты.
    pass
