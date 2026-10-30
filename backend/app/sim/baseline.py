"""Снимок baseline (ТЗ 4.6): pg_dump -Fc, restore с сохранением sim_runs и каталога runs/."""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

import psycopg
from psycopg.conninfo import make_conninfo
from psycopg.types.json import Jsonb

from app.config import get_settings
from app.db.session import psycopg_dsn
from app.logging import get_logger
from app.sim.events import dumps as json_dumps

log = get_logger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[3]

RUN_COLS = (
    "id, kind, label, scenario_id, seed, llm_profile_id, reset_mode, parent_run_id, status, "
    "started_sim, finished_sim, started_at, finished_at, resumed_count, summary, settings_snapshot, export_path, notes"
)


class BaselineUnavailableError(Exception):
    """Нет файлов снимка для профиля."""


class BaselineToolingError(Exception):
    """Инструмент снимка или авторемонта недоступен либо завершился ошибкой."""


class BaselineActiveRunError(Exception):
    """Нельзя создать снимок при активном запуске."""


def _pg_tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise BaselineToolingError(f"{name} не найден в PATH")
    return path


def check_tools(server_version: int) -> dict[str, int]:
    """Для roundtrip используем pg_dump/pg_restore той же major-версии, что сервер."""
    versions = {"server": server_version // 10000}
    for name in ("pg_dump", "pg_restore"):
        proc = subprocess.run([_pg_tool(name), "--version"], capture_output=True, text=True, check=False)
        match = re.search(r"PostgreSQL\) (\d+)\.", proc.stdout)
        if proc.returncode or not match:
            raise BaselineToolingError(f"Не удалось определить версию {name}")
        versions[name] = int(match[1])
        if versions[name] != versions["server"]:
            raise BaselineToolingError(f"Нужен {name} major {versions['server']}, установлен {versions[name]}")
    return versions


def baseline_dir() -> Path:
    """Первый существующий каталог снимков или data/baseline в корне репозитория."""
    for candidate in (REPO_ROOT / "data" / "baseline", Path("/data/baseline")):
        if candidate.is_dir():
            return candidate
    default = REPO_ROOT / "data" / "baseline"
    default.mkdir(parents=True, exist_ok=True)
    return default


def runs_export_dir() -> Path:
    for candidate in (REPO_ROOT / "data" / "runs", Path("/data/runs")):
        if candidate.is_dir():
            return candidate
    default = REPO_ROOT / "data" / "runs"
    default.mkdir(parents=True, exist_ok=True)
    return default


def _dump_path(profile: str) -> Path:
    return baseline_dir() / f"{profile}.dump"


def _meta_path(profile: str) -> Path:
    return baseline_dir() / f"{profile}.meta.json"


def _sha_path(profile: str) -> Path:
    return baseline_dir() / f"{profile}.dump.sha256"


def resolve_profile(profile: str | None = None) -> str:
    if profile:
        return profile
    return get_settings().profile


def _load_meta(profile: str) -> dict[str, Any] | None:
    path = _meta_path(profile)
    if not path.is_file():
        return None
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _baseline_run_id_sync(cur: psycopg.Cursor[Any]) -> int | None:
    cur.execute("select id from sim_runs where kind = 'baseline' order by id limit 1")
    row = cur.fetchone()
    return int(row[0]) if row else None


async def _baseline_run_id_async(conn: psycopg.AsyncConnection[Any]) -> int | None:
    cur = await conn.execute("select id from sim_runs where kind = 'baseline' order by id limit 1")
    row = await cur.fetchone()
    return int(row[0]) if row else None


def _seed_meta_sync(cur: psycopg.Cursor[Any]) -> dict[str, Any] | None:
    cur.execute("select value from settings where key = 'seed_done'")
    row = cur.fetchone()
    if not row or row[0] is None:
        return None
    val = row[0]
    return val if isinstance(val, dict) else json.loads(val)


async def _seed_meta_async(conn: psycopg.AsyncConnection[Any]) -> dict[str, Any] | None:
    cur = await conn.execute("select value from settings where key = 'seed_done'")
    row = await cur.fetchone()
    if not row or row[0] is None:
        return None
    val = row[0]
    return val if isinstance(val, dict) else json.loads(val)


def info(profile: str | None = None) -> dict[str, Any]:
    prof = resolve_profile(profile)
    dump_path = _dump_path(prof)
    base: dict[str, Any] = {
        "available": False,
        "path": None,
        "profile": prof,
        "seed": None,
        "size_bytes": None,
        "sha256": None,
        "created_at": None,
        "baseline_run_id": None,
    }
    if not dump_path.is_file():
        return base
    meta = _load_meta(prof) or {}
    sha_path = _sha_path(prof)
    sha = sha_path.read_text(encoding="utf-8").strip().split()[0] if sha_path.is_file() else None
    if sha is None:
        sha = _sha256_file(dump_path)
    base.update(
        {
            "available": True,
            "path": str(dump_path),
            "profile": meta.get("profile", prof),
            "seed": meta.get("seed"),
            "size_bytes": dump_path.stat().st_size,
            "sha256": sha,
            "created_at": meta.get("created_at"),
            "baseline_run_id": meta.get("baseline_run_id"),
        }
    )
    return base


def _write_artifacts(profile: str, dump_path: Path, meta: dict[str, Any]) -> None:
    _sha_path(profile).write_text(f"{_sha256_file(dump_path)}  {dump_path.name}\n", encoding="utf-8")
    _meta_path(profile).write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def _run_pg_dump(dsn: str, dump_path: Path) -> None:
    cmd = [
        _pg_tool("pg_dump"),
        "-Fc",
        "--no-owner",
        "--no-acl",
        "--exclude-table=public.sim_runs",
        "-f",
        str(dump_path),
        dsn,
    ]
    log.info("baseline_dump_start", path=str(dump_path))
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise BaselineToolingError(f"pg_dump завершился с кодом {proc.returncode}: {proc.stderr.strip()[-500:]}")


def dump_for_connection(
    conn: psycopg.Connection[Any], profile: str | None = None, *, database_url: str | None = None
) -> dict[str, Any]:
    """Синхронный dump после сида (scripts/seed/run.py)."""
    prof = resolve_profile(profile)
    with conn.cursor() as cur:
        seed_done = _seed_meta_sync(cur)
        baseline_run_id = _baseline_run_id_sync(cur)
        if seed_done and seed_done.get("run_id"):
            baseline_run_id = int(seed_done["run_id"])
        seed = int(seed_done["seed"]) if seed_done and seed_done.get("seed") is not None else get_settings().sim_seed
        if seed_done and seed_done.get("profile"):
            prof = str(seed_done["profile"])
    dump_path = _dump_path(prof)
    dump_path.parent.mkdir(parents=True, exist_ok=True)
    dsn = psycopg_dsn(database_url)
    _run_pg_dump(dsn, dump_path)
    meta = {
        "profile": prof,
        "seed": seed,
        "baseline_run_id": baseline_run_id,
        "created_at": dt.datetime.now(dt.UTC).isoformat(),
    }
    _write_artifacts(prof, dump_path, meta)
    log.info("baseline_dump_done", profile=prof, bytes=dump_path.stat().st_size)
    return info(prof)


def _connection_dsn(conn: psycopg.AsyncConnection[Any]) -> str:
    # info.dsn исключает пароль. Сохраняем аутентификацию, но не выбираем другую БД из Settings.
    return make_conninfo(conn.info.dsn, password=conn.info.password)


async def dump(conn: psycopg.AsyncConnection[Any], profile: str | None = None) -> dict[str, Any]:
    """Создать снимок baseline из текущего состояния БД."""
    prof = resolve_profile(profile)
    seed_done = await _seed_meta_async(conn)
    baseline_run_id = await _baseline_run_id_async(conn)
    if seed_done and seed_done.get("run_id"):
        baseline_run_id = int(seed_done["run_id"])
    seed = int(seed_done["seed"]) if seed_done and seed_done.get("seed") is not None else get_settings().sim_seed
    if seed_done and seed_done.get("profile"):
        prof = str(seed_done["profile"])
    dump_path = _dump_path(prof)
    dump_path.parent.mkdir(parents=True, exist_ok=True)
    dsn = _connection_dsn(conn)
    await conn.commit()
    _run_pg_dump(dsn, dump_path)
    meta = {
        "profile": prof,
        "seed": seed,
        "baseline_run_id": baseline_run_id,
        "created_at": dt.datetime.now(dt.UTC).isoformat(),
    }
    _write_artifacts(prof, dump_path, meta)
    return info(prof)


async def _fetch_sim_runs(conn: psycopg.AsyncConnection[Any]) -> list[tuple[Any, ...]]:
    cur = await conn.execute(f"select {RUN_COLS} from sim_runs order by id")  # noqa: S608
    return list(await cur.fetchall())


async def _restore_sim_runs(conn: psycopg.AsyncConnection[Any], rows: list[tuple[Any, ...]]) -> None:
    # Baseline уже восстановлен: удаление sim_runs каскадно удалило бы его данные.
    if not rows:
        return
    columns = RUN_COLS.split(", ")
    placeholders = ", ".join(["%s"] * len(columns))
    cols_sql = ", ".join(RUN_COLS.split(", "))
    status_idx = RUN_COLS.split(", ").index("status")
    for row in rows:
        data = [Jsonb(value) if isinstance(value, dict | list) else value for value in row]
        if data[status_idx] in ("running", "paused", "interrupted"):
            data[status_idx] = "interrupted"
        await conn.execute(
            f"insert into sim_runs ({cols_sql}) overriding system value values ({placeholders}) "
            "on conflict (id) do update set " + ", ".join(f"{col} = excluded.{col}" for col in columns if col != "id"),
            tuple(data),
        )
    await conn.execute(
        "select setval(pg_get_serial_sequence('sim_runs', 'id'), coalesce((select max(id) from sim_runs), 1))"
    )


def _run_pg_restore(dsn: str, dump_path: Path) -> None:
    cmd = [
        _pg_tool("pg_restore"),
        "--clean",
        "--if-exists",
        "--no-owner",
        "--no-acl",
        "-d",
        dsn,
        str(dump_path),
    ]
    log.info("baseline_restore_pg_start", path=str(dump_path))
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        # pg_restore часто возвращает 1 при harmless warnings
        err = proc.stderr or proc.stdout or ""
        if proc.returncode > 1 or "FATAL" in err.upper():
            raise BaselineToolingError(f"pg_restore завершился с кодом {proc.returncode}: {err.strip()[-800:]}")


def _csi_repair_script() -> Path:
    # Нативный checkout и Docker используют тот же CLI с единственной логикой ремонта.
    path = REPO_ROOT / "scripts" / "seed" / "repair_csi.py"
    if not path.is_file():
        raise BaselineToolingError("не найден scripts/seed/repair_csi.py; baseline не восстановлен")
    return path


def _run_csi_repair(dsn: str, script: Path) -> dict[str, Any]:
    # DSN передаём окружением, а не argv; отдельный процесс изолирует logging seed-модулей.
    proc = subprocess.run(
        [sys.executable, str(script), "--apply", "--json"],
        env={**os.environ, "DATABASE_URL": dsn},
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        result: dict[str, Any] = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        log.error("baseline_csi_repair_failed", returncode=proc.returncode, detail=proc.stderr[-2000:])
        raise BaselineToolingError("CSI-ремонт не вернул результат; восстановление baseline не завершено") from exc
    if (
        proc.returncode != 0
        or not isinstance(result, dict)
        or not all(isinstance(result.get(key), int) for key in ("after", "total", "added"))
        or result.get("after") != result.get("total")
    ):
        reason = (
            result.get("error", "неполное покрытие или неверный результат")
            if isinstance(result, dict)
            else "неверный результат"
        )
        raise BaselineToolingError(f"Автоматический CSI-ремонт: {reason}; восстановление baseline не завершено")
    log.info("baseline_csi_repair_done", **result)
    return result


async def _notify(conn: psycopg.AsyncConnection[Any], event_type: str, job_id: str) -> None:
    await conn.execute(
        "select pg_notify('runs', %s)",
        (json_dumps({"type": event_type, "job_id": job_id}),),
    )


async def restore(
    conn: psycopg.AsyncConnection[Any],
    *,
    profile: str | None = None,
    pause: bool = False,
) -> str:
    """Откат БД к снимку baseline; sim_runs и runs/ восстанавливаются отдельно."""
    prof = resolve_profile(profile)
    dump_path = _dump_path(prof)
    if not dump_path.is_file():
        raise BaselineUnavailableError(f"снимок baseline для профиля {prof} не найден")
    repair_script = _csi_repair_script()
    job_id = str(uuid.uuid4())
    dsn = _connection_dsn(conn)
    runs_dir = runs_export_dir()
    runs_backup: Path | None = None
    if runs_dir.is_dir() and any(runs_dir.iterdir()):
        runs_backup = baseline_dir() / f".restore_runs_{job_id}"
        if runs_backup.exists():
            shutil.rmtree(runs_backup)
        shutil.copytree(runs_dir, runs_backup)

    sim_rows = await _fetch_sim_runs(conn)
    await _notify(conn, "baseline_restore_started", job_id)
    await conn.commit()
    await conn.close()

    try:
        _run_pg_restore(dsn, dump_path)
    except Exception:
        if runs_backup and runs_backup.is_dir():
            shutil.rmtree(runs_backup, ignore_errors=True)
        raise

    async with await psycopg.AsyncConnection.connect(dsn, autocommit=False) as new_conn:
        await _restore_sim_runs(new_conn, sim_rows)
        if runs_backup and runs_backup.is_dir():
            if runs_dir.exists():
                shutil.rmtree(runs_dir)
            shutil.copytree(runs_backup, runs_dir)
            shutil.rmtree(runs_backup, ignore_errors=True)
        # CLI открывает свою транзакцию: сохранённые sim_runs должны быть видны до ремонта.
        await new_conn.commit()
        await asyncio.to_thread(_run_csi_repair, dsn, repair_script)
        await _notify(new_conn, "baseline_restore_finished", job_id)
        await new_conn.commit()

    log.info("baseline_restore_done", profile=prof, job_id=job_id, pause=pause)
    return job_id
