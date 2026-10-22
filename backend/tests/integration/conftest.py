"""Интеграционные тесты: нужна PostgreSQL. DATABASE_URL_TEST (или DATABASE_URL); без неё тесты пропускаются."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import psycopg
import pytest

ROOT = Path(__file__).resolve().parents[3]
URL = os.environ.get("DATABASE_URL_TEST") or os.environ.get("DATABASE_URL")


def _dsn(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


@pytest.fixture(scope="session")
def db_url() -> str:
    if not URL:
        pytest.skip("нет DATABASE_URL_TEST — интеграционные тесты пропущены")
    try:
        with psycopg.connect(_dsn(URL), connect_timeout=3):
            pass
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"PostgreSQL недоступна: {exc}")
    return URL


@pytest.fixture(scope="session")
def migrated_db(db_url: str) -> str:
    """Чистая схема → alembic upgrade head. Возвращает URL."""
    with psycopg.connect(_dsn(db_url), autocommit=True) as c:
        c.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    env = {**os.environ, "DATABASE_URL": db_url}
    r = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT / "backend",
        env=env,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr[-2000:]
    return db_url


@pytest.fixture
def conn(migrated_db: str):
    with psycopg.connect(_dsn(migrated_db), autocommit=True) as c:
        yield c


def _seed(url: str, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "DATABASE_URL": url}
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "seed" / "run.py"), "--profile", "lite", "--clients", "200", *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )


@pytest.fixture(scope="session")
def seeded(migrated_db: str) -> str:
    """Чистая схема + alembic head + сид lite на 200 клиентов (общая для test_coverage и test_sim)."""
    with psycopg.connect(_dsn(migrated_db), autocommit=True) as c:
        c.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    r = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT / "backend",
        env={**os.environ, "DATABASE_URL": migrated_db},
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr[-2000:]
    r = _seed(migrated_db)
    assert r.returncode == 0, r.stderr[-3000:]
    return migrated_db
