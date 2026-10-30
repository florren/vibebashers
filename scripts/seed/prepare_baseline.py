"""#108: конвертация старого архива только в пустой изолированной PostgreSQL 16.

Исходный dump неизменяем; результат — отдельный архив текущей схемы. Рабочая БД
не используется. Пропущенный sim_runs восстанавливается из run_id и seed_done
самого архива с явной пометкой о восстановленной метаинформации.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app.sim.baseline import (
    BaselineToolingError,
    _csi_repair_script,
    _run_csi_repair,
    _sha256_file,
)


def command(argv: list[str], *, dsn: str | None = None) -> None:
    env = dict(os.environ)
    if dsn:
        keys = {
            "host": "PGHOST",
            "port": "PGPORT",
            "user": "PGUSER",
            "password": "PGPASSWORD",
            "dbname": "PGDATABASE",
            "sslmode": "PGSSLMODE",
        }
        env.update({keys[key]: value for key, value in conninfo_to_dict(dsn).items() if key in keys})
    result = subprocess.run(argv, env=env, capture_output=True, text=True, check=False)
    if result.returncode:
        # Не включаем DSN и SQL/COPY-строки в сообщение об ошибке.
        raise BaselineToolingError(f"{Path(argv[0]).name}: код {result.returncode}; конвертация остановлена")


def prepare(
    source: Path,
    output: Path,
    dsn: str,
    restore_tool: str,
    dump_tool: str,
    psql_tool: str,
) -> dict[str, str]:
    if source.resolve() == output.resolve() or output.exists():
        raise BaselineToolingError("Нужен новый выходной файл; существующие архивы не перезаписываются")
    source_hash = _sha256_file(source)
    with psycopg.connect(dsn, autocommit=True) as conn:
        if conn.info.server_version // 10000 != 16:
            raise BaselineToolingError("Изолированная БД должна быть PostgreSQL 16")
        if conn.execute(
            "select 1 from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.nspname='public' limit 1"
        ).fetchone():
            raise BaselineToolingError("Изолированная БД должна быть пустой; изменения не начаты")
        schema = (ROOT / "contracts/db/schema.sql").read_text()
        runs_ddl = schema[schema.index("CREATE TABLE sim_runs (") :]
        runs_ddl = runs_ddl[: runs_ddl.index("\n);") + 3]
        conn.execute(runs_ddl)
        with tempfile.TemporaryDirectory(prefix="cx-baseline-") as directory:
            for section in ("pre-data", "data", "post-data"):
                raw = Path(directory) / f"{section}.sql"
                command(
                    [
                        restore_tool,
                        "--no-owner",
                        "--no-acl",
                        f"--section={section}",
                        "-f",
                        str(raw),
                        str(source),
                    ]
                )
                # Единственная известная несовместимая настройка pg_dump 18 → PG16.
                # Потоковая обработка: COPY-данные архива не загружаются в память.
                compatible = raw.with_suffix(".pg16.sql")
                with raw.open() as src, compatible.open("w") as dst:
                    in_copy = False
                    for line in src:
                        if in_copy or line != "SET transaction_timeout = 0;\n":
                            dst.write(line)
                        if line.startswith("COPY ") and line.rstrip().endswith("FROM stdin;"):
                            in_copy = True
                        elif line.rstrip() == "\\.":
                            in_copy = False
                command(
                    [psql_tool, "-X", "-v", "ON_ERROR_STOP=1", "-f", str(compatible)],
                    dsn=dsn,
                )
                if section == "data":
                    seed = conn.execute("select value from settings where key='seed_done'").fetchone()
                    if not seed or not seed[0].get("run_id"):
                        raise BaselineToolingError("В архиве нет seed_done.run_id; метаданные baseline неизвестны")
                    marker = seed[0]
                    columns = conn.execute(
                        "select table_name,column_name from information_schema.columns where table_schema='public' and column_name in ('run_id','sim_run_id')"
                    ).fetchall()
                    ids = {int(marker["run_id"])}
                    for table, column in columns:
                        rows = conn.execute(
                            sql.SQL("select distinct {} from {} where {} is not null").format(
                                sql.Identifier(column),
                                sql.Identifier(table),
                                sql.Identifier(column),
                            )
                        ).fetchall()
                        ids.update(int(row[0]) for row in rows)
                    when = conn.execute("select sim_time from sim_state where id=1").fetchone()[0]
                    for rid in sorted(ids):
                        baseline = rid == int(marker["run_id"])
                        conn.execute(
                            "insert into sim_runs(id,kind,label,seed,status,started_sim,notes) overriding system value values(%s,%s,%s,%s,%s,%s,%s)",
                            (
                                rid,
                                "baseline" if baseline else "free",
                                "Baseline (метаданные из архива)" if baseline else "История (метаданные из архива)",
                                int(marker.get("seed", 42)),
                                "completed" if baseline else "interrupted",
                                when,
                                "Архив не содержал sim_runs; метаданные восстановлены из seed_done/run_id; исходные записи запуска неизвестны",
                            ),
                        )
                    conn.execute("update sim_runs set finished_sim=started_sim where kind='baseline'")
                    conn.execute(
                        "select setval(pg_get_serial_sequence('sim_runs','id'),(select max(id) from sim_runs))"
                    )
            result = subprocess.run(
                [sys.executable, "-m", "alembic", "upgrade", "head"],
                cwd=ROOT / "backend",
                env={
                    **os.environ,
                    "DATABASE_URL": dsn.replace("postgresql://", "postgresql+psycopg://", 1),
                },
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode:
                raise BaselineToolingError("Миграции изолированной БД завершились ошибкой; выходной архив не создан")
            conn.execute(
                "ALTER TABLE sim_runs ADD COLUMN IF NOT EXISTS public_id text GENERATED ALWAYS AS ('SR-' || lpad(id::text,4,'0')) STORED"
            )
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS sim_runs_public_id_uidx ON sim_runs(public_id)")
            conn.execute(
                "ALTER TABLE sim_runs ADD CONSTRAINT sim_runs_scenario_fk FOREIGN KEY(scenario_id) REFERENCES scenarios(id)"
            )
            conn.execute(
                "ALTER TABLE sim_runs ADD CONSTRAINT sim_runs_llm_profile_fk FOREIGN KEY(llm_profile_id) REFERENCES llm_profiles(id)"
            )
            _run_csi_repair(dsn, _csi_repair_script())
            # Дамп текущей схемы должен быть читаем штатным pg_restore 16.
            version = subprocess.run([dump_tool, "--version"], capture_output=True, text=True, check=True)
            if "PostgreSQL) 16." not in version.stdout:
                raise BaselineToolingError("Для выходного архива нужен pg_dump 16")
            staged = Path(directory) / "prepared.dump"
            command(
                [
                    dump_tool,
                    "-Fc",
                    "--no-owner",
                    "--no-acl",
                    "-f",
                    str(staged),
                ],
                dsn=dsn,
            )
            if _sha256_file(source) != source_hash:
                raise BaselineToolingError("Исходный архив изменился во время конвертации")
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open("xb") as dest, staged.open("rb") as src:
                shutil.copyfileobj(src, dest)
    report = {
        "source_sha256": source_hash,
        "output_sha256": _sha256_file(output),
        "output": str(output),
    }
    output.with_suffix(output.suffix + ".sha256").write_text(f"{report['output_sha256']}  {output.name}\n")
    output.with_suffix(output.suffix + ".provenance.json").write_text(json.dumps(report, indent=2))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pg-restore", default="pg_restore")
    parser.add_argument("--pg-dump", default="pg_dump")
    parser.add_argument("--psql", default="psql")
    args = parser.parse_args()
    try:
        result = prepare(
            args.source,
            args.output,
            os.environ["BASELINE_SCRATCH_URL"],
            args.pg_restore,
            args.pg_dump,
            args.psql,
        )
    except (BaselineToolingError, KeyError) as exc:
        parser.exit(1, f"{exc}\n")
    sys.stdout.write(json.dumps(result) + "\n")


if __name__ == "__main__":
    main()
