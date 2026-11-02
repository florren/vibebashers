"""T-240: ограниченный локальный разбор отзывов и отделённый от входа модели gold."""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
import re
import zipfile
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit
from xml.etree.ElementTree import ParseError
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from defusedxml.common import DefusedXmlException
from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException
from openpyxl.xml import DEFUSEDXML
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.contracts.enums import Channel, Criticality, ProductLine, Sentiment

ROOT = Path(__file__).resolve().parents[3]
MAX_BYTES = 10_000_000
MAX_ROWS = 10_000
MAX_COLUMNS = 16


class CorpusError(ValueError):
    pass


class Platform(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    code: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{1,31}$")]
    name_ru: Annotated[str, Field(min_length=1, max_length=100)]
    name_en: Annotated[str, Field(min_length=1, max_length=100)]
    type: Literal["review_portal", "telegram_channel", "app_store", "forum", "other"]

    @field_validator("name_ru", "name_en")
    @classmethod
    def text_only(cls, value: str) -> str:
        if re.search(r"https?://|www\.|<[^>]+>|\b[\w-]+\.(ru|com|org|net|invalid)\b", value, re.I):
            raise ValueError("название площадки должно быть текстом без URL/HTML")
        return value


class ReviewGold(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    product_line: ProductLine
    criticality: Criticality
    sentiment: Sentiment | None = None

    @field_validator("product_line")
    @classmethod
    def actual_direction(cls, value: ProductLine) -> ProductLine:
        if value == ProductLine.OTHER:
            raise ValueError("корпус должен содержать одно из 15 направлений")
        return value


class ReviewRow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    external_id: Annotated[str, Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.:-]+$")]
    date: str
    channel: Channel
    text: Annotated[str, Field(min_length=1, max_length=8000)]
    source_platform: str
    source_url: Annotated[str, Field(min_length=1, max_length=2048)]
    gold: ReviewGold | None = None

    @field_validator("source_url")
    @classmethod
    def provenance_url(cls, value: str) -> str:
        if any(ord(char) < 33 or ord(char) == 127 for char in value):
            raise ValueError("source_url содержит пробельные/control символы")
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        if (
            parsed.scheme not in ("https", "http")
            or not host
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
        ):
            raise ValueError("source_url должен быть HTTP(S) URL без credentials/fragment")
        return value


def platforms(path: Path | None = None) -> dict[str, Platform]:
    data = yaml.safe_load((path or ROOT / "data/platforms.yaml").read_text(encoding="utf-8"))
    rows = [Platform.model_validate(x) for x in data["platforms"]]
    if not rows or len({x.code for x in rows}) != len(rows):
        raise CorpusError("коды площадок должны быть непустыми и уникальными")
    return {x.code: x for x in rows}


def source_time(value: str, timezone: str | None = None) -> dt.datetime:
    """Дата без времени требует явной зоны; datetime без offset не принимается."""
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        if not timezone:
            raise CorpusError("для даты без времени требуется --timezone")
        try:
            return dt.datetime.combine(dt.date.fromisoformat(value), dt.time(), tzinfo=ZoneInfo(timezone))
        except (ValueError, ZoneInfoNotFoundError) as exc:
            raise CorpusError("некорректная дата или timezone") from exc
    try:
        result = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CorpusError("некорректная дата источника") from exc
    if result.utcoffset() is None:
        raise CorpusError("datetime источника требует явного UTC offset")
    return result


def _xlsx(raw: bytes) -> list[dict[str, Any]]:
    if not DEFUSEDXML:
        raise CorpusError("для XLSX требуется defusedxml")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            if len(archive.infolist()) > 1000 or sum(x.file_size for x in archive.infolist()) > 50_000_000:
                raise CorpusError("превышен предел распакованного XLSX")
        workbook = load_workbook(io.BytesIO(raw), read_only=True, data_only=False, keep_links=False)
        try:
            if len(workbook.worksheets) != 1:
                raise CorpusError("ожидается один лист отзывов")
            sheet = workbook.worksheets[0]
            if sheet.max_column and sheet.max_column > MAX_COLUMNS:
                raise CorpusError("слишком много столбцов")
            cells = sheet.iter_rows()
            header = next(cells, ())
            names = [x.value for x in header]
            if not names or any(not isinstance(x, str) for x in names) or len(set(names)) != len(names):
                raise CorpusError("некорректные или повторяющиеся заголовки")
            rows = []
            for index, row in enumerate(cells, 1):
                if index > MAX_ROWS:
                    raise CorpusError("слишком много строк")
                if any(x.data_type == "f" for x in row):
                    raise CorpusError("формулы в отзывах не допускаются")
                if any(x.value is not None for x in row):
                    values = [x.value for x in row]
                    if any(isinstance(x, (dt.datetime, dt.date)) for x in values):
                        raise CorpusError("даты XLSX должны быть строками ISO с явной timezone")
                    rows.append(dict(zip(names, values, strict=True)))
            return rows
        finally:
            workbook.close()
    except CorpusError:
        raise
    except (ValueError, KeyError, zipfile.BadZipFile, DefusedXmlException, ParseError, InvalidFileException) as exc:
        raise CorpusError("некорректный XLSX") from exc


def parse_reviews(path: Path, *, timezone: str | None = None, synthetic_only: bool = False) -> list[ReviewRow]:
    with path.open("rb") as source:
        raw = source.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise CorpusError("файл превышает 10 MB")
    try:
        if path.suffix.lower() == ".json":
            values = json.loads(raw)
        elif path.suffix.lower() == ".csv":
            reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
            names = reader.fieldnames
            if not names or len(names) > MAX_COLUMNS or len(set(names)) != len(names):
                raise CorpusError("некорректные заголовки CSV")
            values = []
            for index, csv_row in enumerate(reader, 1):
                if index > MAX_ROWS:
                    raise CorpusError("слишком много строк")
                values.append(csv_row)
        elif path.suffix.lower() == ".xlsx":
            values = _xlsx(raw)
        else:
            raise CorpusError("поддерживаются JSON/CSV/XLSX")
    except (json.JSONDecodeError, UnicodeDecodeError, csv.Error) as exc:
        raise CorpusError("некорректный файл отзывов") from exc
    if not isinstance(values, list) or not 1 <= len(values) <= MAX_ROWS:
        raise CorpusError("ожидается от 1 до 10000 отзывов")
    result = []
    known = platforms()
    ids = set()
    for index, value in enumerate(values, 1):
        if not isinstance(value, dict):
            raise CorpusError(f"строка {index}: ожидается объект")
        obj = dict(value)
        # CSV/XLSX передают аннотацию отдельной JSON-ячейкой, а не произвольными колонками.
        if isinstance(obj.get("gold"), str):
            try:
                obj["gold"] = json.loads(obj["gold"]) if obj["gold"] else None
            except json.JSONDecodeError as exc:
                raise CorpusError(f"строка {index}: некорректная аннотация") from exc
        row = ReviewRow.model_validate(obj)
        source_time(row.date, timezone)
        if synthetic_only:
            url = urlsplit(row.source_url)
            if url.scheme != "https" or not (url.hostname or "").endswith(".invalid"):
                raise CorpusError("seed corpus требует HTTPS source_url в reserved .invalid")
        if row.source_platform not in known or row.external_id in ids:
            raise CorpusError(f"строка {index}: неизвестная площадка или повтор external_id")
        ids.add(row.external_id)
        result.append(row)
    return result


def message(row: ReviewRow, *, run_id: int, timezone: str | None = None) -> tuple[dict[str, Any], dt.datetime]:
    if isinstance(run_id, bool) or not isinstance(run_id, int) or run_id <= 0:
        raise CorpusError("run_id должен быть положительным int")
    at = source_time(row.date, timezone)
    # Gold намеренно не копируется ни в meta, ни в classification, ни в текст.
    return {
        "external_id": f"run:{run_id}:{row.external_id}",
        "channel": row.channel.value,
        "client": {},
        "text": row.text,
        "timestamp": at.isoformat(),
        "geo": {"source": "none"},
        "origin": "api",
        "meta": {"source_platform": row.source_platform, "source_url": row.source_url, "source_date": row.date},
    }, at


@lru_cache(maxsize=1)
def _display_catalog() -> Mapping[str, Platform]:
    return MappingProxyType(platforms())


def project_platform(code: object) -> dict[str, str] | None:
    """Будущий producer получает только известный display DTO, никогда raw meta/URL."""
    if not isinstance(code, str):
        return None
    platform = _display_catalog().get(code)
    if platform is None:
        return None
    return {"code": platform.code, "name_ru": platform.name_ru, "name_en": platform.name_en, "type": platform.type}
