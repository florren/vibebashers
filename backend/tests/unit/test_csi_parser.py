from __future__ import annotations

import datetime as dt
import io
import json
import zipfile

import pytest
from openpyxl import Workbook

from app.ingest.csi import CsiError, parse_json, parse_xlsx, validate_row

BASE = {"csi_no": "CSI-001", "complaint_ru": "Учебная жалоба на долгое ожидание", "branch_code": "0042"}


def xlsx_bytes(rows) -> bytes:
    book = Workbook()
    for row in rows:
        book.active.append(row)
    stream = io.BytesIO()
    book.save(stream)
    book.close()
    return stream.getvalue()


def test_json_single_array_and_localized_values() -> None:
    assert len(parse_json(json.dumps(BASE).encode())) == 1
    rows = parse_json(json.dumps([BASE, BASE]).encode())
    assert [r.number for r in rows] == [1, 2]
    value = validate_row(
        {
            **BASE,
            "wait_min": "1,255",
            "waiting_count": "1 234",
            "received_at": "09.11.2026 10:30",
            "products": "deposit;debit_card",
        }
    )
    assert value["wait_min"] == 1.26
    assert value["waiting_count"] == 1234
    assert value["received_at"] == "2026-11-09T10:30:00+03:00"
    assert value["products"] == ["deposit", "debit_card"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("waiting_count", -1),
        ("waiting_count", 1.5),
        ("waiting_count", 32768),
        ("waiting_count", True),
        ("wait_min", float("nan")),
        ("wait_min", float("inf")),
        ("wait_min", 1000000),
        ("received_at", 45123),
        ("received_at", "bad-date"),
        ("tenure_org_days", 2147483648),
        ("products", ["unknown"]),
        ("csi_no", "123"),
        ("complaint_ru", ""),
        ("ФИО", "Реальное имя"),
    ],
)
def test_invalid_column_is_named(field, value) -> None:
    with pytest.raises(CsiError) as error:
        validate_row({**BASE, field: value})
    assert error.value.column == field


def test_xlsx_headers_dates_and_rows() -> None:
    raw = xlsx_bytes(
        [
            ["Номер обращения", "Текст обращения", "ВСП", "Время ожидания (мин)", "Дата обращения"],
            ["CSI-002", "Учебная жалоба", "0042", "2,5", dt.datetime(2026, 11, 9, 12, 30)],
        ]
    )
    rows = parse_xlsx(raw)
    assert rows[0].number == 2
    row = validate_row(rows[0].value)
    assert row["branch_code"] == "0042" and row["wait_min"] == 2.5
    assert row["received_at"] == "2026-11-09T12:30:00+03:00"
    assert rows[0].columns["wait_min"] == "Время ожидания (мин)"


@pytest.mark.parametrize("raw", [b"", b"not a ZIP", b"PKbad"])
def test_corrupt_xlsx_is_error(raw) -> None:
    with pytest.raises(CsiError, match="XLSX"):
        parse_xlsx(raw)


def test_duplicate_header_and_xml_entities_rejected() -> None:
    with pytest.raises(CsiError, match="повтор"):
        parse_xlsx(xlsx_bytes([["csi_no", "Номер обращения"], ["CSI-001", "CSI-002"]]))
    raw = xlsx_bytes([["csi_no", "complaint_ru", "branch_code"], ["CSI-001", "Учебная жалоба", "0042"]])
    target = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(raw)) as source, zipfile.ZipFile(target, "w") as output:
        for info in source.infolist():
            blob = source.read(info.filename)
            if info.filename == "xl/worksheets/sheet1.xml":
                blob = b'<!DOCTYPE worksheet [<!ENTITY forbidden "EXPAND">]>' + blob.replace(
                    "Учебная".encode(), b"&forbidden;"
                )
            output.writestr(info, blob)
    with pytest.raises(CsiError, match="XLSX"):
        parse_xlsx(target.getvalue())


def test_json_syntax_error_has_physical_position() -> None:
    with pytest.raises(CsiError) as error:
        parse_json(b"[\ninvalid]")
    assert error.value.row == 2
    assert error.value.column == "JSON column 1"
