"""T-021: единый загрузчик и строгая проверка канонических golden/lite корпусов."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
GOLDEN_DIR = ROOT / "data/golden"
BENCH_DIR = ROOT / "data/bench"
CLASSIFICATION_CODES = frozenset({"golden_v1", "lite_v1"})
GOLD_FIELDS = ("signal_type", "product", "system", "criticality", "complexity", "team", "flags", "needs_hitl")
HARD_TAGS = frozenset({"sarcasm", "multi_topic", "implicit_product"})


def dataset_path(code: str) -> Path:
    if not code or Path(code).name != code or code in {".", ".."}:
        raise ValueError("недопустимый код набора")
    folders = (GOLDEN_DIR, BENCH_DIR) if code in CLASSIFICATION_CODES else (BENCH_DIR, GOLDEN_DIR)
    for folder in folders:
        path = folder / f"{code}.jsonl"
        if path.is_file():
            return path
    raise FileNotFoundError(f"набор {code!r} не найден")


def read_rows(path: Path, *, complete_gold: bool = False) -> list[dict[str, Any]]:
    """Не подменяет повреждённые строки пустыми данными и не печатает исходные тексты."""
    definitions = json.loads((ROOT / "contracts/events/common.schema.json").read_text())["$defs"]
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path.name}:{line_number}: неверный JSON") from exc
        prefix = f"{path.name}:{line_number}"
        if not isinstance(row, dict) or not isinstance(row.get("text"), str) or not row["text"].strip():
            raise ValueError(f"{prefix}: нужен объект с непустым text")
        external_id = row.get("id")
        if complete_gold and (not isinstance(external_id, str) or not external_id.strip()):
            raise ValueError(f"{prefix}: нужен стабильный id")
        if external_id is not None:
            if not isinstance(external_id, str) or external_id in seen:
                raise ValueError(f"{prefix}: некорректный или повторяющийся id")
            seen.add(external_id)
        if row.get("channel") not in definitions["channel"]["enum"]:
            raise ValueError(f"{prefix}: неизвестный channel")
        if row.get("segment") is not None and row["segment"] not in definitions["segment"]["enum"]:
            raise ValueError(f"{prefix}: неизвестный segment")
        tags = row.get("tags", [])
        if (
            not isinstance(tags, list)
            or any(not isinstance(tag, str) or not tag for tag in tags)
            or len(set(tags)) != len(tags)
        ):
            raise ValueError(f"{prefix}: tags должен быть списком уникальных строк")
        gold = row.get("gold")
        if not isinstance(gold, dict) or not gold:
            raise ValueError(f"{prefix}: нужен непустой gold")
        if complete_gold:
            if set(gold) != set(GOLD_FIELDS):
                raise ValueError(f"{prefix}: нужен полный gold {GOLD_FIELDS}")
            for key in GOLD_FIELDS[:-2]:
                value = gold[key]
                if value is None and key in ("product", "system"):
                    continue
                if value not in definitions[key]["enum"]:
                    raise ValueError(f"{prefix}: неизвестный gold.{key}")
            flags = gold["flags"]
            if (
                not isinstance(flags, list)
                or any(not isinstance(flag, str) or flag not in definitions["flag"]["enum"] for flag in flags)
                or len(set(flags)) != len(flags)
            ):
                raise ValueError(f"{prefix}: неверные gold.flags")
            if type(gold["needs_hitl"]) is not bool:
                raise ValueError(f"{prefix}: gold.needs_hitl должен быть boolean")
            annotation = row.get("annotation")
            if (
                not isinstance(annotation, dict)
                or not isinstance(annotation.get("rationale_ru"), str)
                or len(annotation["rationale_ru"]) < 40
            ):
                raise ValueError(f"{prefix}: отсутствует основание разметки")
        rows.append(row)
    if not rows:
        raise ValueError(f"{path.name}: пустой набор")
    return rows


def validate_pair(golden: list[dict[str, Any]], lite: list[dict[str, Any]]) -> None:
    if not 200 <= len(golden) <= 300 or not 30 <= len(lite) <= 40:
        raise ValueError("ТЗ14.3: golden 200–300, lite 30–40 кейсов")
    by_id = {row["id"]: row for row in golden}
    if len(by_id) != len(golden):
        raise ValueError("повторяющийся golden id")
    if len({row["text"].casefold().strip() for row in golden}) != len(golden):
        raise ValueError("повторяющиеся тексты golden")
    for row in lite:
        if by_id.get(row["id"]) != row:
            raise ValueError("lite не является точным подмножеством golden")
        if "ambiguous" in row.get("tags", []):
            raise ValueError("ambiguous не входит в lite gate")
    if len(lite) >= len(golden):
        raise ValueError("lite должен быть строгим подмножеством")
    definitions = json.loads((ROOT / "contracts/events/common.schema.json").read_text())["$defs"]
    for label, rows in (("golden", golden), ("lite", lite)):
        if sum(bool(HARD_TAGS.intersection(row.get("tags", []))) for row in rows) * 10 < len(rows) * 3:
            raise ValueError(f"{label}: менее30% сложных текстов")
        for field, enum in (("signal_type", "signal_type"), ("channel", "channel")):
            counts = Counter(row["gold"][field] if field == "signal_type" else row[field] for row in rows)
            if set(counts) != set(definitions[enum]["enum"]) or max(counts.values()) - min(counts.values()) > 1:
                raise ValueError(f"{label}: несбалансированные {field}")


def load_rows(code: str) -> list[dict[str, Any]]:
    return read_rows(dataset_path(code), complete_gold=code in CLASSIFICATION_CODES)


def check_canonical() -> dict[str, int]:
    golden, lite = (load_rows(code) for code in ("golden_v1", "lite_v1"))
    validate_pair(golden, lite)
    for code, rows in (("golden_v1", golden), ("lite_v1", lite)):
        mirror = BENCH_DIR / f"{code}.jsonl"
        if read_rows(mirror, complete_gold=True) != rows:
            raise ValueError(f"legacy mirror {mirror.name} расходится с canonical")
    return {"golden_v1": len(golden), "lite_v1": len(lite)}
