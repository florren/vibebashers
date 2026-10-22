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

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.seed.clients import ensure_history_run, seed_clients, seed_history_signals, seed_operations  # noqa: E402
from scripts.seed.common import PROFILES, connect, get_setting, log, set_setting  # noqa: E402
from scripts.seed.coverage import compute_coverage  # noqa: E402
from scripts.seed.refs import seed_all_refs  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default="lite", choices=sorted(PROFILES))
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--database-url", default=None)
    ap.add_argument("--refs-only", action="store_true")
    ap.add_argument(
        "--reset-history", action="store_true", help="удалить клиентов и историю перед сидом (справочники остаются)"
    )
    ap.add_argument("--clients", type=int, default=None, help="переопределить число клиентов профиля")
    a = ap.parse_args()
    prof = PROFILES[a.profile]
    n_clients = a.clients or prof["clients"]
    t0 = time.perf_counter()
    rnd = random.Random(a.seed)
    sim_now = dt.datetime(
        2026, 11, 9, 9, 0, tzinfo=dt.timezone(dt.timedelta(hours=3))
    )  # «сегодня» симуляции = день демо
    with connect(a.database_url) as conn, conn.cursor() as cur:
        seed_all_refs(cur, rnd)
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
        run_id = ensure_history_run(cur, a.seed, sim_now, a.profile)
        seed_operations(cur, rnd, run_id, sim_now)
        conn.commit()
        seed_history_signals(cur, rnd, run_id, sim_now, prof["signals"], prof["incidents"], a.seed)
        conn.commit()
        cov = compute_coverage(cur, run_id)
        set_setting(
            cur,
            "seed_done",
            {
                "profile": a.profile,
                "seed": a.seed,
                "clients": n_clients,
                "run_id": run_id,
                "at": dt.datetime.now(dt.UTC).isoformat(),
            },
        )
        if get_setting(cur, "setup_completed") is None:
            set_setting(cur, "setup_completed", False)
        cur.execute(
            "insert into sim_state (id, sim_time, day_no, speed, running, seed, phase, current_run_id) values (1, %s, 0, 60, false, %s, 'morning', %s) on conflict (id) do update set current_run_id = coalesce(sim_state.current_run_id, excluded.current_run_id)",
            (sim_now, a.seed, run_id),
        )
        conn.commit()
    log.info(
        "seed_done",
        profile=a.profile,
        seconds=round(time.perf_counter() - t0, 1),
        coverage_ok=cov["sla_cells_ok"] and not cov["signal_combos_missing"],
    )
    return 0 if cov["sla_cells_ok"] and not cov["signal_combos_missing"] else 2


if __name__ == "__main__":
    sys.exit(main())
