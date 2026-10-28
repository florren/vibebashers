#!/usr/bin/env python3
"""Ручной импорт синтетических CSI-файлов через API, без прямых INSERT (T-246)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx
import structlog


def main() -> int:
    structlog.configure(
        processors=[structlog.processors.JSONRenderer(ensure_ascii=False)],
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
    )
    log = structlog.get_logger("import_csi")
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path, nargs="?", default=Path("data/import/csi"))
    parser.add_argument("--base", default="http://localhost:8000")
    args = parser.parse_args()
    files = (
        sorted(p for p in args.path.iterdir() if p.suffix.lower() in (".json", ".xlsx"))
        if args.path.is_dir()
        else [args.path]
    )
    if not files:
        parser.error("нет JSON/XLSX для импорта")
    failed = False
    with httpx.Client(timeout=30) as client:
        for path in files:
            if path.suffix.lower() == ".xlsx":
                with path.open("rb") as stream:
                    response = client.post(
                        args.base.rstrip("/") + "/api/ingest/csi",
                        files={
                            "file": (
                                path.name,
                                stream,
                                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            )
                        },
                    )
            elif path.suffix.lower() == ".json":
                response = client.post(
                    args.base.rstrip("/") + "/api/ingest/csi",
                    content=path.read_bytes(),
                    headers={"Content-Type": "application/json"},
                )
            else:
                parser.error("ожидается JSON/XLSX")
            if response.status_code not in (202, 422):
                response.raise_for_status()
            body = response.json()
            report = body.get("report", body)
            log.info(
                "csi_import",
                file=path.name,
                status=response.status_code,
                accepted=report["accepted"],
                duplicates=report["duplicates"],
                rejected=report["rejected"],
                errors=[
                    {k: row[k] for k in ("row", "column", "error") if k in row}
                    for row in report["items"]
                    if row["status"] == "rejected"
                ],
            )
            failed = failed or response.status_code == 422
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
