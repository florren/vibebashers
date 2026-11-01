#!/usr/bin/env python3
"""Сид данных: `python scripts/seed/run.py --profile lite|demo|stress [--seed 42] [--reset-history] [--refs-only]`.

Идемпотентно: справочники — upsert по коду; клиенты/история — только если ещё не созданы; флаг settings.seed_done.
После сида считает матрицу покрытия → settings.coverage. Нужен DATABASE_URL (schema через alembic upgrade head)."""

from __future__ import annotations

import argparse
import datetime as dt
import random
import sys
import time
from pathlib import Path
from typing import Any

import psycopg

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
for _candidate in (_ROOT / "backend", Path("/app")):
    if (_candidate / "app" / "sim" / "baseline.py").exists() and str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))

from app.sim import baseline as baseline_svc  # noqa: E402
from app.sim.baseline import BaselineToolingError  # noqa: E402

from scripts.seed.clients import (  # noqa: E402
    ensure_history_run,
    seed_clients,
    seed_history_signals,
    seed_operations,
)
from scripts.seed.common import PROFILES, connect, get_setting, log, set_setting  # noqa: E402
from scripts.seed.coverage import compute_coverage  # noqa: E402
from scripts.seed.refs import seed_all_refs  # noqa: E402


def preserve_existing(cur: psycopg.Cursor[Any], profile: str) -> int | None:
    """Повтор install — только чтение. None означает действительно пустую БД."""
    # Backend создаёт sim_state ещё до первого seed. Это служебное состояние,
    # а не признак заполненного банка; реальные клиенты/запуски по-прежнему защищены.
    existing = cur.execute("select exists(select 1 from clients) or exists(select 1 from sim_runs)").fetchone()[0]
    if not existing:
        return None
    seed_done = get_setting(cur, "seed_done")
    if not isinstance(seed_done, dict) or not seed_done.get("run_id"):
        log.error(
            "seed_existing_incomplete",
            message="Данные уже есть, но seed_done отсутствует. Нужна ручная диагностика; сброс не выполнялся",
        )
        return 4
    run_id = seed_done["run_id"]
    if not cur.execute("select 1 from sim_runs where id=%s and kind='baseline'", (run_id,)).fetchone():
        log.error(
            "seed_existing_incomplete",
            message="Baseline-запуск из seed_done не найден; данные сохранены",
        )
        return 4
    cov = compute_coverage(cur, run_id, persist=False)
    ok = cov["sla_cells_ok"] and not cov["signal_combos_missing"]
    (log.info if ok else log.warning)(
        "seed_existing_preserved",
        profile=seed_done.get("profile"),
        requested_profile=profile,
        coverage_ok=ok,
        missing=cov["signal_combos_missing"],
        baseline_available=baseline_svc.info(seed_done.get("profile") or profile)["available"],
        message="Существующие данные и настройки сохранены; seed и baseline dump не выполнялись",
    )
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default="lite", choices=sorted(PROFILES))
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--database-url", default=None)
    ap.add_argument("--refs-only", action="store_true")
    ap.add_argument(
        "--if-needed",
        action="store_true",
        help="для установки: существующие данные только проверить, не изменять",
    )
    ap.add_argument(
        "--reset-history",
        action="store_true",
        help="удалить клиентов и историю перед сидом (справочники остаются)",
    )
    ap.add_argument(
        "--clients",
        type=int,
        default=None,
        help="переопределить число клиентов профиля",
    )
    ap.add_argument("--branch-provider", choices=["synthetic", "snapshot_file"], default="synthetic")
    ap.add_argument("--branch-file", type=Path, default=None)
    a = ap.parse_args()
    if a.if_needed and (a.reset_history or a.refs_only):
        ap.error("--if-needed несовместим с --reset-history и --refs-only")
    prof = PROFILES[a.profile]
    n_clients = a.clients or prof["clients"]
    t0 = time.perf_counter()
    sim_now = dt.datetime(
        2026, 11, 9, 9, 0, tzinfo=dt.timezone(dt.timedelta(hours=3))
    )  # «сегодня» симуляции = день демо
    with connect(a.database_url) as conn, conn.cursor() as cur:
        if not a.refs_only:
            try:
                versions = baseline_svc.check_tools(conn.info.server_version)
            except BaselineToolingError as exc:
                log.error("seed_tooling_failed", reason=str(exc))
                return 3
            log.info("baseline_tools_ready", **versions)
        if a.if_needed:
            result = preserve_existing(cur, a.profile)
            if result is not None:
                return result
        previous = cur.execute("select seed from sim_state where id = 1").fetchone()
        seed = a.seed if a.seed is not None else (int(previous[0]) if previous and previous[0] is not None else 42)
        rnd = random.Random(seed)
        seed_all_refs(
            cur,
            rnd,
            seed=seed,
            sim_time=sim_now,
            branch_mode=a.branch_provider,
            branch_snapshot=a.branch_file,
        )
        conn.commit()
        if a.refs_only:
            return 0
        if a.reset_history:
            cur.execute(
                "truncate signals, incidents, operations, faults, client_states, client_products, accounts, clients, sim_runs restart identity cascade"
            )
            cur.execute("delete from settings where key in ('seed_done', 'coverage')")
            conn.commit()
        seed_clients(cur, rnd, n_clients, sim_now)
        conn.commit()
        run_id = ensure_history_run(cur, seed, sim_now, a.profile)
        seed_operations(cur, rnd, run_id, sim_now)
        conn.commit()
        seed_history_signals(cur, rnd, run_id, sim_now, prof["signals"], prof["incidents"], seed)
        conn.commit()
        cov = compute_coverage(cur, run_id)
        if not cov["sla_cells_ok"] or cov["signal_combos_missing"]:
            conn.commit()
            log.error(
                "seed_coverage_failed",
                missing=cov["signal_combos_missing"],
                sla_cells=cov["sla_cells"],
            )
            return 2
        previous_seed_done = get_setting(cur, "seed_done")
        set_setting(
            cur,
            "seed_done",
            {
                "profile": a.profile,
                "seed": seed,
                "clients": n_clients,
                "run_id": run_id,
                "at": dt.datetime.now(dt.UTC).isoformat(),
            },
        )
        if get_setting(cur, "setup_completed") is None:
            set_setting(cur, "setup_completed", False)
        cur.execute(
            "insert into sim_state (id, sim_time, day_no, speed, running, seed, phase, current_run_id) values (1, %s, 0, 60, false, %s, 'morning', %s) on conflict (id) do update set current_run_id = coalesce(sim_state.current_run_id, excluded.current_run_id)",
            (sim_now, seed, run_id),
        )
        conn.commit()
        try:
            baseline_svc.dump_for_connection(conn, a.profile, database_url=a.database_url)
        except BaselineToolingError as exc:
            if previous_seed_done is None:
                cur.execute("delete from settings where key='seed_done'")
            else:
                set_setting(cur, "seed_done", previous_seed_done)
            conn.commit()
            log.error("baseline_dump_failed", reason=str(exc))
            return 3
    log.info(
        "seed_done",
        profile=a.profile,
        seconds=round(time.perf_counter() - t0, 1),
        coverage_ok=cov["sla_cells_ok"] and not cov["signal_combos_missing"],
    )
    return 0 if cov["sla_cells_ok"] and not cov["signal_combos_missing"] else 2


if __name__ == "__main__":
    sys.exit(main())
