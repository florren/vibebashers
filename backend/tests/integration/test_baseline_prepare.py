"""#108: конвертация архива в пустой БД без подмены источника и повторный restore."""

import importlib.util
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

from app.sim import baseline
from tests.helpers import dsn

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("prepare_baseline", ROOT / "scripts/seed/prepare_baseline.py")
prepare_baseline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare_baseline)


def test_prepare_and_restore_keep_source(seeded, tmp_path, monkeypatch):
    source = tmp_path / "old.dump"
    output = tmp_path / "compatible.dump"
    baseline._run_pg_dump(dsn(seeded), source)
    before = baseline._sha256_file(source)
    database = "cx_prepare_" + uuid4().hex
    scratch = urlsplit(dsn(seeded))._replace(path="/" + database).geturl()
    with psycopg.connect(dsn(seeded), autocommit=True) as admin:
        admin.execute(sql.SQL("create database {}").format(sql.Identifier(database)))
        try:
            # Клиенты в CI16 и native18 оба проходят один безопасный путь подготовки.
            result = prepare_baseline.prepare(
                source,
                output,
                scratch,
                baseline._pg_tool("pg_restore"),
                baseline._pg_tool("pg_dump"),
                baseline._pg_tool("psql"),
            )
            assert result["source_sha256"] == before == baseline._sha256_file(source)
            assert output.with_suffix(".dump.provenance.json").is_file()
            for _ in range(2):
                baseline._run_pg_restore(scratch, output)
                repair = baseline._run_csi_repair(scratch, baseline._csi_repair_script())
                assert repair["added"] == 0 and repair["after"] == repair["total"] == 480
            with psycopg.connect(scratch) as conn:
                assert conn.execute("select version_num from alembic_version").fetchone()[0] == "0010"
                assert conn.execute("select count(*) from clients").fetchone()[0] == 200
            with psycopg.connect(scratch, autocommit=True) as conn:
                conn.execute("update clients set display_name='rollback-marker' where id=(select min(id) from clients)")
            original_run = baseline.subprocess.run

            def corrupt_sql(command, **kwargs):
                result = original_run(command, **kwargs)
                if command[0].endswith("pg_restore") and "-f" in command and result.returncode == 0:
                    path = Path(command[command.index("-f") + 1])
                    with path.open("a") as handle:
                        handle.write("\nselect * from deliberately_missing_restore_table;\n")
                return result

            with monkeypatch.context() as context:
                context.setattr(baseline.subprocess, "run", corrupt_sql)
                with pytest.raises(baseline.BaselineToolingError, match="транзакция восстановления отменена"):
                    baseline._run_pg_restore(scratch, output)
            with psycopg.connect(scratch) as conn:
                assert (
                    conn.execute("select display_name from clients order by id limit 1").fetchone()[0]
                    == "rollback-marker"
                )
            with pytest.raises(baseline.BaselineToolingError, match="пустой"):
                prepare_baseline.prepare(source, tmp_path / "refused.dump", scratch, "pg_restore", "pg_dump", "psql")
            assert not (tmp_path / "refused.dump").exists()
            with pytest.raises(baseline.BaselineToolingError, match="перезаписываются"):
                prepare_baseline.prepare(source, source, scratch, "pg_restore", "pg_dump", "psql")
        finally:
            admin.execute(sql.SQL("drop database {} with (force)").format(sql.Identifier(database)))
