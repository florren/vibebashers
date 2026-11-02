#!/usr/bin/env python3
"""T-042: явный пересчёт summary завершённого запуска (make run-summary ID=…)."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import psycopg  # noqa: E402

from app.db.session import psycopg_dsn  # noqa: E402
from app.logging import get_logger  # noqa: E402
from app.sim.events import dumps  # noqa: E402
from app.sim.run_summary import build_summary  # noqa: E402

log = get_logger(__name__)


async def recalculate(run_id: int) -> int:
    async with await psycopg.AsyncConnection.connect(psycopg_dsn()) as conn:
        row = await (await conn.execute("select status from sim_runs where id=%s for update", (run_id,))).fetchone()
        if row is None:
            log.error("run_summary_not_found", run_id=run_id)
            return 2
        if row[0] not in ("stopped", "completed"):
            log.error("run_summary_not_finished", run_id=run_id, status=row[0])
            return 2
        summary = await build_summary(conn, run_id, refresh_economics=True)
        await conn.execute("update sim_runs set summary=%s::jsonb where id=%s", (dumps(summary), run_id))
        log.info("run_summary_updated", run_id=run_id, summary_version=summary["summary_version"])
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--id", type=int, required=True)
    args = parser.parse_args()
    if args.id < 1:
        parser.error("--id must be positive")
    return asyncio.run(recalculate(args.id))


if __name__ == "__main__":
    raise SystemExit(main())
