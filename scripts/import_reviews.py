"""T-240: локальный JSON/CSV/XLSX dataset -> UnifiedMessage, без HTTP/парсинга сайтов.

По умолчанию только проверка файла. --apply требует явный run_id и собственный
DATABASE_URL оператора; ENV_FILE=/dev/null рекомендуется для воспроизводимого CLI.
Аннотация gold никогда не используется как runtime-классификация.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import psycopg  # noqa: E402
from app.corpus.importer import import_reviews  # noqa: E402
from app.corpus.reviews import CorpusError, parse_reviews  # noqa: E402
from app.db.session import psycopg_dsn  # noqa: E402
from app.sim.maintenance import MaintenanceBusy  # noqa: E402
from app.sim.maintenance_db import public_operation  # noqa: E402
from pydantic import ValidationError  # noqa: E402


async def apply(path: Path, *, run_id: int, source_code: str, timezone: str | None) -> dict[str, int]:
    rows = parse_reviews(path, timezone=timezone)
    # URL только из явно переданного окружения; конфигурацию приложения/мастер не читаем.
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise CorpusError("для --apply требуется DATABASE_URL")
    async with public_operation(url):
        async with await psycopg.AsyncConnection.connect(psycopg_dsn(url)) as conn:
            return await import_reviews(conn, rows, run_id=run_id, source_code=source_code, timezone=timezone)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--timezone")
    parser.add_argument("--run-id", type=int)
    parser.add_argument("--source-code", default="product_lines_v1")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        if args.apply:
            if args.run_id is None or args.run_id <= 0:
                raise CorpusError("для --apply требуется положительный --run-id")
            result = asyncio.run(
                apply(args.path, run_id=args.run_id, source_code=args.source_code, timezone=args.timezone)
            )
        else:
            result = {"validated": len(parse_reviews(args.path, timezone=args.timezone))}
    except (CorpusError, ValidationError, OSError, psycopg.Error, MaintenanceBusy) as exc:
        # Ошибки библиотеки могут содержать URL, SQL или строку файла — не печатаем их.
        detail = str(exc) if isinstance(exc, CorpusError) else type(exc).__name__
        parser.exit(1, detail + "\n")
    sys.stdout.write(json.dumps(result) + "\n")


if __name__ == "__main__":
    main()
