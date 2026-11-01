"""T-265: неизменяемые доказательства финансового эффекта."""
from pathlib import Path
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql((Path(__file__).resolve().parents[2] / "migrations" / "0008_financial_evidence.sql").read_text())


def downgrade() -> None:
    # Аддитивная таблица и аудит сохраняются при откате приложения; история не удаляется.
    pass
