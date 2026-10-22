#!/usr/bin/env python3
"""Регенерация backend/app/db/models.py из живой БД, на которой применён contracts/db/schema.sql (T-005).

Нужна PostgreSQL: DATABASE_URL (или аргумент). Схема применяется в временную схему? Нет — проще: скрипт сам создаёт
временную БД <db>_gen, применяет schema.sql, запускает sqlacodegen (declarative, nojoined, noindexes, без представлений)
и удаляет временную БД. Индексы и представления в моделях не нужны: источник истины для них — schema.sql, а alembic
сравнивает только таблицы/колонки/ограничения (см. backend/alembic/env.py include_object)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "backend/app/db/models.py"
HEADER = '"""СГЕНЕРИРОВАНО scripts/gen_models.py (sqlacodegen) из contracts/db/schema.sql — не редактировать руками.\n\nИсточник истины — schema.sql; при изменении контракта: make sync-contracts (с DATABASE_URL) → этот файл обновится.\nИндексы и представления намеренно не включены (их сравнение отключено в alembic/env.py)."""\n'


def main() -> int:
    url = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("DATABASE_URL", "")).replace(
        "postgresql+psycopg://", "postgresql://"
    )
    if not url:
        print("gen_models: DATABASE_URL не задан — пропуск (models.py не обновлён)")  # noqa: T201
        return 0
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    info = conninfo_to_dict(url)
    gen_db = f"{info.get('dbname', 'cx_pulse')}_gen"
    admin = make_conninfo(**{**info, "dbname": "postgres"})
    gen_url = make_conninfo(**{**info, "dbname": gen_db})
    host = str(info.get("host", "localhost"))
    auth = str(info.get("user", "")) + (f":{info['password']}" if info.get("password") else "")
    sa_url = (
        f"postgresql+psycopg://{auth}@/{gen_db}?host={host}&port={info.get('port', 5432)}"
        if host.startswith("/")
        else f"postgresql+psycopg://{auth}@{host}:{info.get('port', 5432)}/{gen_db}"
    )
    with psycopg.connect(admin, autocommit=True) as c:
        c.execute(f'DROP DATABASE IF EXISTS "{gen_db}"')
        c.execute(f'CREATE DATABASE "{gen_db}"')
    try:
        with psycopg.connect(gen_url, autocommit=True) as c:
            c.execute((ROOT / "contracts/db/schema.sql").read_text(encoding="utf-8"))
        sqlacodegen = ROOT / "backend/.venv/bin/sqlacodegen"
        exe = str(sqlacodegen) if sqlacodegen.exists() else "sqlacodegen"
        r = subprocess.run(
            [exe, "--generator", "declarative", "--options", "nojoined,noindexes", "--noviews", sa_url],
            capture_output=True,
            text=True,
            check=True,
        )
        OUT.write_text(HEADER + r.stdout, encoding="utf-8")
        print(f"models: {r.stdout.count(chr(10) + 'class ')} классов → {OUT.relative_to(ROOT)}")  # noqa: T201
    finally:
        with psycopg.connect(admin, autocommit=True) as c:
            c.execute(f'DROP DATABASE IF EXISTS "{gen_db}"')
    return 0


if __name__ == "__main__":
    sys.exit(main())
