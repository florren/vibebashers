"""T-240: содержательные synthetic review fixtures, локальные форматы и provenance."""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
from collections import Counter
from pathlib import Path

import pytest
import yaml
from openpyxl import Workbook
from pydantic import ValidationError

from app.contracts.enums import Channel, ProductLine
from app.corpus.reviews import CorpusError, Platform, message, parse_reviews, source_time
from app.corpus.seed_plan import coverage_plan

ROOT = Path(__file__).resolve().parents[3]
CORPUS = ROOT / "data/corpus/reviews/product_lines_v1/reviews.json"


def test_corpus_count_proportions_and_full_delivery_plan() -> None:
    rows = parse_reviews(CORPUS)
    refs = yaml.safe_load((ROOT / "data/product_lines.yaml").read_text())["product_lines"]
    manifest = yaml.safe_load(CORPUS.with_name("manifest.yaml").read_text())
    assert len(rows) == 162 == manifest["rows"]
    assert hashlib.sha256(CORPUS.read_bytes()).hexdigest() == manifest["sha256"]
    assert Counter(x.gold.product_line for x in rows if x.gold) == {r["code"]: r["demo_review_share"] * 3 for r in refs}
    lines = frozenset(ProductLine(r["code"]) for r in refs)
    plan = coverage_plan(rows, lines)
    assert len(plan) == len({x.external_id for x in plan}) == 180
    assert {(x.product_line, x.channel) for x in plan} == {(line, channel) for line in lines for channel in Channel}
    assert len({x.text for x in rows}) == 162
    assert min(len(x.text.split()) for x in rows) >= 9


def test_formats_equivalent_and_gold_not_model_input(tmp_path: Path) -> None:
    original = json.loads(CORPUS.read_text())[:2]
    source = tmp_path / "reviews.json"
    source.write_text(json.dumps(original))
    expected = parse_reviews(source)
    fields = list(original[0])
    csv_path = tmp_path / "reviews.csv"
    with csv_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows({**x, "gold": json.dumps(x["gold"])} for x in original)
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(fields)
    for row in original:
        sheet.append([json.dumps(row[x]) if x == "gold" else row[x] for x in fields])
    xlsx = tmp_path / "reviews.xlsx"
    workbook.save(xlsx)
    workbook.close()
    assert parse_reviews(csv_path) == parse_reviews(xlsx) == expected
    msg, at = message(expected[0], run_id=42)
    assert "gold" not in json.dumps(msg) and "classification" not in msg
    assert "product_line" not in msg["meta"]
    assert at == dt.datetime.fromisoformat(original[0]["date"])
    assert msg["timestamp"] == at.isoformat()
    assert message(expected[0], run_id=43)[0]["external_id"] != msg["external_id"]


def test_date_only_requires_explicit_timezone() -> None:
    with pytest.raises(CorpusError):
        source_time("2026-10-01")
    assert source_time("2026-10-01", "Europe/Moscow").utcoffset() == dt.timedelta(hours=3)
    assert source_time("2026-10-01T03:00:00+03:00") == source_time("2026-10-01T00:00:00Z")
    for value in ["2026-10-01T01:00:00", "not-a-date"]:
        with pytest.raises(CorpusError):
            source_time(value)


@pytest.mark.parametrize("name", ["https://real.ru", "www.site.com", "<a>Площадка</a>"])
def test_display_catalog_rejects_urls_and_html(name: str) -> None:
    with pytest.raises(ValidationError):
        Platform(code="test", name_ru=name, name_en="Reviews", type="other")


def test_duplicate_and_unknown_platform_rejected(tmp_path: Path) -> None:
    row = json.loads(CORPUS.read_text())[0]
    p = tmp_path / "r.json"
    p.write_text(json.dumps([row, row]))
    with pytest.raises(CorpusError):
        parse_reviews(p)
    row["source_platform"] = "unknown"
    p.write_text(json.dumps([row]))
    with pytest.raises(CorpusError):
        parse_reviews(p)


def test_xlsx_formula_and_multiple_sheets_rejected(tmp_path: Path) -> None:
    p = tmp_path / "bad.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["external_id", "text"])
    sheet.append(["x", "=1+1"])
    workbook.save(p)
    with pytest.raises(CorpusError, match="формулы"):
        parse_reviews(p)
    workbook.create_sheet("Extra")
    workbook.save(p)
    workbook.close()
    with pytest.raises(CorpusError, match="один лист"):
        parse_reviews(p)


def test_reserved_source_url_and_run_id_guard(tmp_path: Path) -> None:
    row = json.loads(CORPUS.read_text())[0]
    row["source_url"] = "https://real.example.com/private"
    p = tmp_path / "r.json"
    p.write_text(json.dumps([row]))
    with pytest.raises(CorpusError):
        parse_reviews(p, synthetic_only=True)
    assert parse_reviews(p)[0].source_url == row["source_url"]
    original = parse_reviews(CORPUS)[0]
    for run_id in [0, -1, True]:
        with pytest.raises(CorpusError):
            message(original, run_id=run_id)


@pytest.mark.parametrize(
    "url", ["file:///tmp/test", "https://user:secret@test.invalid/x", "https://test.invalid/x#fragment"]
)
def test_source_urls_never_credentials_or_nonreserved_scheme(tmp_path: Path, url: str) -> None:
    row = json.loads(CORPUS.read_text())[0]
    row["source_url"] = url
    p = tmp_path / "bad.json"
    p.write_text(json.dumps([row]))
    with pytest.raises(ValidationError):
        parse_reviews(p)


@pytest.mark.parametrize("payload", [b"{}", b"[]", b"[1]", b"broken", b'"rows"'])
def test_invalid_json_shapes_rejected(tmp_path: Path, payload: bytes) -> None:
    p = tmp_path / "bad.json"
    p.write_bytes(payload)
    with pytest.raises(CorpusError):
        parse_reviews(p)


def test_csv_headers_encoding_and_size_bounds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.corpus.reviews as module

    p = tmp_path / "bad.csv"
    for content in [b"text,text\nx,y\n", b"\xff"]:
        p.write_bytes(content)
        with pytest.raises(CorpusError):
            parse_reviews(p)
    monkeypatch.setattr(module, "MAX_BYTES", 10)
    p.write_bytes(b"x" * 11)
    with pytest.raises(CorpusError, match="10 MB"):
        parse_reviews(p)


def test_xlsx_requires_secure_xml_and_valid_archive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.corpus.reviews as module

    p = tmp_path / "bad.xlsx"
    p.write_bytes(b"not-an-archive")
    with pytest.raises(CorpusError, match="некорректный XLSX"):
        parse_reviews(p)
    monkeypatch.setattr(module, "DEFUSEDXML", False)
    with pytest.raises(CorpusError, match="defusedxml"):
        parse_reviews(p)


def test_platform_projection_only_known_catalog_and_never_raw_meta() -> None:
    from app.corpus.reviews import project_platform

    for value in [
        None,
        {"code": "client_voice", "source_url": "https://private.invalid"},
        "https://real.ru",
        "unknown",
    ]:
        assert project_platform(value) is None
    public = project_platform("client_voice")
    assert public == {
        "code": "client_voice",
        "name_ru": "Отзывы клиентов",
        "name_en": "Customer reviews",
        "type": "review_portal",
    }


def test_missing_gold_and_wrong_direction_plan_refused() -> None:
    rows = parse_reviews(CORPUS)
    with pytest.raises(CorpusError):
        coverage_plan([rows[0].model_copy(update={"gold": None})], frozenset({ProductLine.DEPOSITS}))
    with pytest.raises(CorpusError):
        coverage_plan(rows[:1], frozenset({ProductLine.DEPOSITS, ProductLine.MORTGAGE}))


def _cli():
    import importlib.util

    spec = importlib.util.spec_from_file_location("review_import_cli", ROOT / "scripts/import_reviews.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cli_dry_run_does_not_need_database(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import sys

    cli = _cli()
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(sys, "argv", ["import_reviews.py", str(CORPUS)])
    cli.main()
    assert json.loads(capsys.readouterr().out) == {"validated": 162}


def test_cli_apply_requires_explicit_run_and_database(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import sys

    cli = _cli()
    monkeypatch.delenv("DATABASE_URL", raising=False)
    for extra in [[], ["--run-id", "1"]]:
        monkeypatch.setattr(sys, "argv", ["import_reviews.py", str(CORPUS), "--apply", *extra])
        with pytest.raises(SystemExit) as error:
            cli.main()
        assert error.value.code == 1
        assert capsys.readouterr().err


def test_cli_library_errors_do_not_print_input(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import sys

    import psycopg

    cli = _cli()

    async def failed(*args, **kwargs):
        raise psycopg.OperationalError("synthetic-sensitive-marker")

    monkeypatch.setattr(cli, "apply", failed)
    monkeypatch.setattr(sys, "argv", ["import_reviews.py", str(CORPUS), "--apply", "--run-id", "1"])
    with pytest.raises(SystemExit):
        cli.main()
    assert "synthetic-sensitive-marker" not in capsys.readouterr().err


def test_generic_provenance_and_xlsx_external_relationships_have_zero_egress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import socket
    import zipfile

    row = json.loads(CORPUS.read_text())[0]
    row["source_url"] = "https://reviews.example.org/item/42"
    fields = list(row)
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(fields)
    sheet.append([json.dumps(row[key]) if key == "gold" else row[key] for key in fields])
    sheet.cell(2, fields.index("source_url") + 1).hyperlink = "http://127.0.0.1:1/never-fetch"
    p = tmp_path / "external.xlsx"
    workbook.save(p)
    workbook.close()
    with zipfile.ZipFile(p) as archive:
        assert any(
            b'TargetMode="External"' in archive.read(name) for name in archive.namelist() if name.endswith(".rels")
        )

    def forbidden(*args, **kwargs):
        raise AssertionError("локальный parser попытался обратиться к сети")

    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    parsed = parse_reviews(p)
    assert parsed[0].source_url == row["source_url"]  # Не hyperlink target.
    with pytest.raises(CorpusError, match="reserved"):
        parse_reviews(p, synthetic_only=True)


def test_verified_seed_manifest_and_checksum(tmp_path: Path) -> None:
    import shutil

    from app.corpus.seed_plan import load_seed_corpus

    assert len(load_seed_corpus()) == 162
    for name in ("reviews.json", "manifest.yaml"):
        shutil.copyfile(CORPUS.with_name(name), tmp_path / name)
    p = tmp_path / "reviews.json"
    p.write_bytes(p.read_bytes() + b" ")
    with pytest.raises(CorpusError, match="checksum"):
        load_seed_corpus(tmp_path)
