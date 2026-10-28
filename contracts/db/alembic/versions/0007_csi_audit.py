"""T-246: audit CSI natural/composite keys."""
from pathlib import Path

from alembic import op

revision="0007"
down_revision="0006"
branch_labels=None
depends_on=None


def upgrade() -> None:
    op.get_bind().exec_driver_sql((Path(__file__).resolve().parents[2]/"migrations"/"0007_csi_audit.sql").read_text())


def downgrade() -> None:
    # Backward-compatible audit fix is retained; no columns or data are removed.
    pass
