"""T-121: durable Telegram channel без FK в восстанавливаемый bank baseline."""
from pathlib import Path
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql(
        (Path(__file__).resolve().parents[2] / "migrations" / "0015_telegram_transport.sql").read_text()
    )


def downgrade() -> None:
    # Откат кода не удаляет receipts: повтор внешней доставки недопустим.
    pass
