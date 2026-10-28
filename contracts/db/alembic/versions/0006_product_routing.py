"""T-239: безопасный audit product_lines с естественным ключом code."""
from pathlib import Path

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql((Path(__file__).resolve().parents[2] / "migrations" / "0006_product_routing.sql").read_text())


def downgrade() -> None:
    # Исправление audit сохраняется: совместимо со всеми предыдущими таблицами.
    pass
