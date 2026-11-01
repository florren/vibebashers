"""T-208: импорт серверного каталога транскриптов через существующий API."""

from __future__ import annotations

import argparse
import sys
from typing import Any

import httpx
import structlog


def import_transcripts(base: str, *, transport: httpx.BaseTransport | None = None) -> dict[str, Any]:
    with httpx.Client(base_url=base.rstrip("/"), timeout=60, transport=transport) as client:
        response = client.post("/api/ingest/transcripts/import")
        response.raise_for_status()
        report: dict[str, Any] = response.json()
    if not isinstance(report, dict):
        raise ValueError("некорректный ответ импорта: ожидается объект")
    for key in ("files_found", "accepted", "duplicates", "rejected"):
        if type(report.get(key)) is not int or report[key] < 0:
            raise ValueError(f"некорректный ответ импорта: {key}")
    return {key: report[key] for key in ("files_found", "accepted", "duplicates", "rejected")}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://localhost:8000")
    args = parser.parse_args(argv)
    structlog.configure(
        processors=[structlog.processors.JSONRenderer(ensure_ascii=False)],
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
    )
    log = structlog.get_logger("import_transcripts")
    try:
        report = import_transcripts(args.base)
    except (httpx.HTTPError, ValueError) as exc:
        # URL может содержать credentials; наружу выводим только тип ошибки.
        log.error("transcript_import_failed", error_type=type(exc).__name__)
        return 2
    log.info("transcript_import", **report)
    return int(report["rejected"] > 0)


if __name__ == "__main__":
    raise SystemExit(main())
