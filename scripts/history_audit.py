"""#131: read-only аудит по умолчанию; --repair-rejected SIG-N --apply исправляет только выбранный отказ."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import psycopg
from app.db.session import psycopg_dsn
from app.demo.history import audit, repair_rejected


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", default="current", help="current, all или ID запуска")
    parser.add_argument(
        "--repair-rejected", help="SIG-N: восстановить ожидание после отказа человека"
    )
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.apply and not args.repair_rejected:
        parser.error("--apply требует явно выбранного --repair-rejected")
    async with await psycopg.AsyncConnection.connect(psycopg_dsn()) as conn:
        rid = (
            (
                await (
                    await conn.execute(
                        "select current_run_id from sim_state where id=1"
                    )
                ).fetchone()
            )[0]
            if args.run == "current"
            else None
            if args.run == "all"
            else int(args.run)
        )
        if args.run == "current" and rid is None:
            raise ValueError("нет текущего запуска; выберите --run явно")
        before = await audit(conn, rid)
        result = {"audit": before, "applied": False}
        if args.repair_rejected:
            sid = int(args.repair_rejected.removeprefix("SIG-"))
            if rid is None:
                raise ValueError("для восстановления нужен один --run")
            result["selected_signal"] = sid
            if args.apply:
                result["repair"] = await repair_rejected(conn, sid, rid)
                result["applied"] = True
                await conn.commit()
            else:
                await conn.rollback()
        else:
            await conn.rollback()
        sys.stdout.write(
            json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n"
        )


if __name__ == "__main__":
    asyncio.run(main())
