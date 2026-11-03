"""T262: явный retry сохранённого CSI preparation на current paused run.

Не создаёт run и не восстанавливает baseline; требует операторский DATABASE_URL.
На рабочем стенде автоматически не запускается.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.api.common import db  # noqa: E402
from app.llm.run_profiles import capture  # noqa: E402
from app.sim.scenario_acceptance import prepare_csi, require_mock, reserve_csi  # noqa: E402


async def retry(run: int) -> dict:
    async with db() as conn:
        async with conn.transaction():
            require_mock(await capture(conn, None))
        await reserve_csi(conn, run)
        result = await prepare_csi(conn, run)
    # Только агрегаты/provenance: тексты, ПДн и профильные настройки не выводятся.
    return {key: result[key] for key in ("xlsx_sha256", "cohort_sha256", "id_base", "extra_id_base", "registered")}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True, type=int)
    args = parser.parse_args()
    if args.run_id <= 0:
        parser.error("--run-id должен быть положительным")
    print(json.dumps(asyncio.run(retry(args.run_id)), ensure_ascii=False))  # noqa: T201


if __name__ == "__main__":
    main()
