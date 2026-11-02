"""T-108: корреляция audit events с запуском и полная цепочка изменений."""

from pathlib import Path
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql(
        (Path(__file__).resolve().parents[2] / "migrations" / "0011_db_activity_scope.sql").read_text()
    )


def downgrade() -> None:
    # Сохраняем audit evidence при откате приложения: миграция аддитивна.
    pass
