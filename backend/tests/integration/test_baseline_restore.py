"""T-040: dump/restore baseline на seeded БД (нужны pg_dump и pg_restore)."""

from __future__ import annotations

import shutil
from pathlib import Path

import psycopg
import pytest

from app.config import get_settings
from app.sim import baseline as baseline_svc

pytestmark = pytest.mark.skipif(
    not shutil.which("pg_dump") or not shutil.which("pg_restore"),
    reason="pg_dump/pg_restore не найдены в PATH",
)

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def baseline_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(baseline_svc, "baseline_dir", lambda: tmp_path)
    monkeypatch.setattr(baseline_svc, "runs_export_dir", lambda: tmp_path / "runs")
    return tmp_path


async def _count_clients(dsn: str) -> int:
    async with await psycopg.AsyncConnection.connect(dsn, autocommit=True) as conn:
        cur = await conn.execute("select count(*) from clients where is_active")
        row = await cur.fetchone()
        return int(row[0]) if row else 0


@pytest.fixture
def wrong_global_url(monkeypatch: pytest.MonkeyPatch):
    # Переданное соединение — источник истины; глобальная настройка указывает в пустоту.
    monkeypatch.setenv("DATABASE_URL", "postgresql://127.0.0.1:1/not_the_connection?connect_timeout=1")
    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_dump_after_seed_and_restore_roundtrip(seeded: str, baseline_tmp: Path, wrong_global_url) -> None:
    dsn = seeded.replace("postgresql+psycopg://", "postgresql://", 1)
    async with await psycopg.AsyncConnection.connect(dsn, autocommit=False) as conn:
        info = await baseline_svc.dump(conn, profile="lite")
        await conn.commit()
    assert info["available"] is True
    assert (baseline_tmp / "lite.dump").is_file()

    async with await psycopg.AsyncConnection.connect(dsn, autocommit=True) as conn:
        await conn.execute("update clients set is_active = false where id > (select min(id) from clients)")
        after_mutation = await _count_clients(dsn)
        assert after_mutation == 1

    async with await psycopg.AsyncConnection.connect(dsn, autocommit=False) as conn:
        before_restore = await _count_clients(dsn)
        job_id = await baseline_svc.restore(conn, profile="lite")
        assert job_id

    restored = await _count_clients(dsn)
    assert restored > before_restore
