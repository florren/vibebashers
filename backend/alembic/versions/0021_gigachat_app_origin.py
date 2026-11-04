"""GigaChat API balance and explicit application accounting origin."""

from pathlib import Path

from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql(
        (Path(__file__).resolve().parents[2] / "migrations" / "0021_gigachat_app_origin.sql").read_text()
    )


def downgrade() -> None:
    # Forward-only operational audit; downgrading must never reinitialize allowance.
    pass
