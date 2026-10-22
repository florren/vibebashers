"""Общее для сида: подключение, YAML/CSV, журнал, профили, ключи settings."""

from __future__ import annotations

import csv
import json
import os
import sys
from pathlib import Path
from typing import Any

import psycopg
import structlog
import yaml
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
PROFILES = {
    "lite": {"clients": 1000, "signals": 800, "incidents": 150},
    "demo": {"clients": 5000, "signals": 2500, "incidents": 400},
    "stress": {"clients": 20000, "signals": 10000, "incidents": 1500},
}

structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="%H:%M:%S"),
        structlog.dev.ConsoleRenderer(),
    ],
    logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
)
log = structlog.get_logger("seed")


def dsn(url: str | None = None) -> str:
    u = url or os.environ.get("DATABASE_URL") or "postgresql://cx:cx@localhost:5432/cx_pulse"
    return u.replace("postgresql+psycopg://", "postgresql://", 1)


def connect(url: str | None = None) -> psycopg.Connection[Any]:
    return psycopg.connect(dsn(url), autocommit=False)


def load_yaml(rel: str) -> Any:
    return yaml.safe_load((DATA / rel).read_text(encoding="utf-8"))


def load_csv(rel: str) -> list[dict[str, str]]:
    with (DATA / rel).open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def J(v: Any) -> Jsonb:
    return Jsonb(v)


def get_setting(cur: psycopg.Cursor[Any], key: str) -> Any:
    row = cur.execute("select value from settings where key = %s", (key,)).fetchone()
    return row[0] if row else None


def set_setting(cur: psycopg.Cursor[Any], key: str, value: Any) -> None:
    cur.execute(
        "insert into settings (key, value) values (%s, %s) on conflict (key) do update set value = excluded.value, updated_at = now()",
        (key, J(value)),
    )


def count(cur: psycopg.Cursor[Any], table: str) -> int:
    return int(cur.execute(f"select count(*) from {table}").fetchone()[0])  # noqa: S608 — имена таблиц из кода


def dumps(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False)
