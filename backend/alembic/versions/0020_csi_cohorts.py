"""T-248: run/line provenance синтетических CSI знаменателей."""

from pathlib import Path

from alembic import op

revision = "0020"
# Локальная foundation до появления clean0019. Перед PR заменить на0019
# и проверить цепочку19→20; не применять эту ветку к рабочей БД.
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql(
        (Path(__file__).resolve().parents[2] / "migrations" / "0020_csi_cohorts.sql").read_text()
    )


def downgrade() -> None:
    # Рекомендуемый rollback кода сохраняет эти данные. Явный DDL downgrade
    # удаляет только новый CSI sample snapshot; нужен предварительный backup.
    op.execute("DROP VIEW IF EXISTS v_csi_cohort_integrity")
    op.execute("DROP TABLE IF EXISTS csi_cohort_members")
    op.execute("DROP TABLE IF EXISTS csi_cohort_visits")
    op.execute("DROP TABLE IF EXISTS csi_cohorts")
    op.execute("DROP FUNCTION IF EXISTS check_csi_cohort_member_time()")
    op.execute("DROP FUNCTION IF EXISTS immutable_csi_cohort_snapshot()")
    op.execute("DROP INDEX IF EXISTS csi_responses_branch_key")
    op.execute("DROP INDEX IF EXISTS signals_csi_run_key")
