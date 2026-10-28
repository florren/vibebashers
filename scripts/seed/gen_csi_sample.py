#!/usr/bin/env python3
"""Синтетические образцы CSI JSON/XLSX (T-246); ZIP timestamps фиксированы."""

from __future__ import annotations

import datetime as dt
import io
import json
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from openpyxl import Workbook

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    folder = ROOT / "data/import/csi"
    folder.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "csi_no": "CSI-010001",
            "complaint_ru": "Учебная жалоба: долго ждал обслуживания, сотрудник отвечал невежливо.",
            "branch_code": "0042",
            "employee_public_id": "EMP-00003",
            "received_at": "2026-11-09T10:20:00+03:00",
            "ticket_code": "DEMO-A001",
            "waiting_count": 12,
            "serving_count": 4,
            "out_of_order_count": 1,
            "wait_min": 24.5,
            "service_min": 8,
            "redirects": 2,
            "products": ["debit_card"],
            "feedback_type": "жалоба",
            "topic": "вежливость/доброжелательность",
            "subtopic": "общение сотрудника",
        },
        {
            "csi_no": "CSI-010002",
            "complaint_ru": "Учебная жалоба: несколько раз направляли к разным специалистам.",
            "branch_code": "0042",
            "employee_public_id": "EMP-00005",
            "received_at": "2026-11-09T11:10:00+03:00",
            "ticket_code": "DEMO-A002",
            "waiting_count": 7,
            "serving_count": 3,
            "out_of_order_count": 0,
            "wait_min": 15,
            "service_min": 12,
            "redirects": 3,
            "products": ["deposit"],
            "feedback_type": "жалоба",
            "topic": "вежливость/доброжелательность",
            "subtopic": "перенаправления",
        },
    ]
    (folder / "example.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n")
    headers = [
        "Номер обращения",
        "Текст обращения",
        "ВСП",
        "Код сотрудника",
        "Дата обращения",
        "Код талона",
        "Число ожидающих клиентов",
        "Число обслуживающихся клиентов",
        "Число обслуженных вне очереди",
        "Время ожидания (мин)",
        "Время обслуживания (мин)",
        "Число перенаправлений",
        "Оформленные продукты",
        "Тип обратной связи",
        "Тематика",
        "Уточнённая тематика",
    ]
    book = Workbook()
    book.properties.created = book.properties.modified = dt.datetime(2026, 1, 1)
    sheet = book.active
    sheet.title = "Синтетические CSI"
    sheet.append(headers)
    for row in rows:
        values = list(row.values())
        values[4] = dt.datetime.fromisoformat(values[4]).replace(tzinfo=None)
        values[12] = json.dumps(values[12])
        sheet.append(values)
    stream = io.BytesIO()
    book.save(stream)
    book.close()
    with (
        zipfile.ZipFile(io.BytesIO(stream.getvalue())) as source,
        zipfile.ZipFile(folder / "example.xlsx", "w", compression=zipfile.ZIP_DEFLATED) as output,
    ):
        for item in source.infolist():
            info = zipfile.ZipInfo(item.filename, (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            blob = source.read(item.filename)
            if item.filename == "docProps/core.xml":
                core = ET.fromstring(blob)
                for tag in ("created", "modified"):
                    element = core.find("{http://purl.org/dc/terms/}" + tag)
                    if element is not None:
                        element.text = "2026-01-01T00:00:00Z"
                blob = ET.tostring(core, encoding="utf-8")
            output.writestr(info, blob)


if __name__ == "__main__":
    main()
