"""T-268/T-269: обработка поздней информации и публичный чат."""

from pathlib import Path
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql(
        (
            Path(__file__).resolve().parents[2]
            / "migrations"
            / "0010_operator_personal_chat.sql"
        ).read_text()
    )


def downgrade() -> None:
    # Аддитивные очереди и история сохраняются при откате приложения.
    pass
