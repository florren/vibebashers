#!/usr/bin/env python3
"""T-247: генерация локальных synthetic JSON/XLSX; без импорта в БД/сети."""

from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import os
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any

import psycopg
from openpyxl import Workbook

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.sim.csi_corpus import generate


def check_roster(conn: psycopg.Connection[Any], corpus: dict[str, Any]) -> None:
    """Проверка fixture bindings; ошибки не исправляются переназначением сотрудников."""
    actual = {
        (branch, desk): (public_id, position, hired, since)
        for branch, desk, public_id, position, hired, since in conn.execute(
            "SELECT b.code,e.desk_no,e.public_id,e.position,e.hired_sim,e.position_since_sim "
            "FROM branches b JOIN employees e ON e.branch_id=b.id WHERE b.code=ANY(%s)",
            ([e["branch_code"] for e in corpus["employees"]],),
        ).fetchall()
    }
    as_of = dt.datetime.fromisoformat(corpus["metadata"]["as_of"])
    for employee in corpus["employees"]:
        row = actual.get((employee["branch_code"], employee["desk_no"]))
        if row is None or row[:2] != (
            employee["employee_public_id"],
            employee["position"],
        ):
            raise ValueError("CSI fixture roster mismatch; import запрещён")
        if (
            row[2] is None
            or row[3] is None
            or (
                (as_of - row[2]).days != employee["tenure_org_days"]
                or (as_of - row[3]).days != employee["tenure_position_days"]
            )
        ):
            raise ValueError("CSI fixture tenure mismatch; import запрещён")


def xlsx_bytes(rows: list[dict[str, Any]]) -> bytes:
    book = Workbook()
    book.properties.created = book.properties.modified = dt.datetime(2026, 1, 1)
    sheet = book.active
    assert sheet is not None
    sheet.title = "Демонстрационные CSI"
    columns = list(rows[0])
    sheet.append(columns)
    for row in rows:
        # Строковые ISO dates сохраняют offset. Список продуктов — JSON,
        # поддерживаемый штатным validate_row; все тексты из локального YAML.
        sheet.append(
            [
                json.dumps(row[c], ensure_ascii=False)
                if isinstance(row[c], list)
                else row[c]
                for c in columns
            ]
        )
    stream = io.BytesIO()
    book.save(stream)
    book.close()
    output = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(stream.getvalue())) as source,
        zipfile.ZipFile(output, "w") as target,
    ):
        for filename in sorted(source.namelist()):
            blob = source.read(filename)
            if filename == "docProps/core.xml":
                core = ET.fromstring(blob)
                for tag in ("created", "modified"):
                    element = core.find("{http://purl.org/dc/terms/}" + tag)
                    if element is not None:
                        element.text = "2026-01-01T00:00:00Z"
                blob = ET.tostring(core, encoding="utf-8")
            item = zipfile.ZipInfo(filename, (2026, 1, 1, 0, 0, 0))
            item.compress_type = zipfile.ZIP_DEFLATED
            target.writestr(item, blob)
    return output.getvalue()


def write(folder: Path, seed: int | None = None) -> None:
    corpus = generate(seed)
    folder.mkdir(parents=True, exist_ok=True)
    for key in ("metadata", "complaints", "visits", "employees"):
        (folder / f"{key}.json").write_text(
            json.dumps(corpus[key], ensure_ascii=False, indent=2) + "\n"
        )
    (folder / "complaints.xlsx").write_bytes(xlsx_bytes(corpus["complaints"]))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "data/corpus/csi_v1")
    parser.add_argument("--seed", type=int)
    parser.add_argument(
        "--import-output",
        type=Path,
        help="отдельный каталог только JSON/XLSX для T-246",
    )
    parser.add_argument(
        "--check-db",
        action="store_true",
        help="read-only проверка fixture roster через DATABASE_URL_TEST",
    )
    args = parser.parse_args()
    if args.check_db:
        url = os.environ.get("DATABASE_URL_TEST")
        if not url:
            parser.error("--check-db требует DATABASE_URL_TEST (не рабочую БД)")
        with psycopg.connect(
            url.replace("postgresql+psycopg://", "postgresql://", 1)
        ) as conn:
            conn.execute("SET TRANSACTION READ ONLY")
            check_roster(conn, generate(args.seed))
    write(args.output, args.seed)
    if args.import_output:
        args.import_output.mkdir(parents=True, exist_ok=True)
        for filename in ("complaints.json", "complaints.xlsx"):
            (args.import_output / filename).write_bytes(
                (args.output / filename).read_bytes()
            )


if __name__ == "__main__":
    main()
