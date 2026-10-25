"""Проверка словарей i18n фронта (T-156).

Оба файла: валидный JSON, нет пустых строк, enum ENUM_MAP есть в ru и en,
множества листьев равны, множества {{…}} у общего ключа равны.
Пустой объект без листьев ключом не считается.

Использование: python scripts/i18n_check.py  (exit 1 при проблемах).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RU = ROOT / "frontend/src/shared/i18n/ru.json"
EN = ROOT / "frontend/src/shared/i18n/en.json"
COMMON = ROOT / "contracts/events/common.schema.json"

# какие $defs из common.schema.json должны быть переведены и под каким префиксом словаря
ENUM_MAP = {
    "signal_type": "signal.type",
    "flag": "signal.flags",
    "sentiment": "signal.sentiment",
    "complexity": "incident.complexity",
    "criticality": "incident.criticality",
    "severity": "incident.severity",
}

_PLACEHOLDER = re.compile(r"\{\{[^{}]+\}\}")


def walk(d: dict, prefix: str = "") -> list[tuple[str, object]]:
    out: list[tuple[str, object]] = []
    for k, v in d.items():
        key = f"{prefix}.{k}" if prefix else k
        out.extend(walk(v, key) if isinstance(v, dict) else [(key, v)])
    return out


def get(d: dict, path: str) -> dict | None:
    cur: object = d
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur if isinstance(cur, dict) else None


def placeholders(text: str) -> set[str]:
    return set(_PLACEHOLDER.findall(text))


def _read_json(path: Path) -> tuple[object | None, str | None]:
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except json.JSONDecodeError as exc:
        return None, f"{path.name}: невалидный JSON: {exc}"


def collect_problems(ru: dict, en: dict, defs: dict) -> list[str]:
    problems: list[str] = []
    leaves: dict[str, dict[str, object]] = {}
    for label, data in (("ru", ru), ("en", en)):
        found = dict(walk(data))
        leaves[label] = found
        for key, val in found.items():
            if not isinstance(val, str) or not val.strip():
                problems.append(f"{label}: пустое значение: {key}")
        for _name, prefix in ENUM_MAP.items():
            enum = defs.get(_name, {}).get("enum") or []
            section = get(data, prefix) or {}
            for code in enum:
                translated = section.get(code)
                if not isinstance(translated, str) or not translated.strip():
                    problems.append(f"{label}: нет перевода {prefix}.{code}")
    ru_keys = set(leaves["ru"])
    en_keys = set(leaves["en"])
    for key in sorted(ru_keys - en_keys):
        problems.append(f"нет ключа en: {key}")
    for key in sorted(en_keys - ru_keys):
        problems.append(f"лишний ключ en: {key}")
    for key in sorted(ru_keys & en_keys):
        rv, ev = leaves["ru"][key], leaves["en"][key]
        if isinstance(rv, str) and isinstance(ev, str) and placeholders(rv) != placeholders(ev):
            problems.append(f"разные плейсхолдеры: {key}")
    return problems


def main() -> int:
    problems: list[str] = []
    ru, ru_err = _read_json(RU)
    en, en_err = _read_json(EN)
    if ru_err:
        problems.append(ru_err)
    if en_err:
        problems.append(en_err)
    if isinstance(ru, dict) and isinstance(en, dict):
        raw_defs, defs_err = _read_json(COMMON)
        if defs_err:
            problems.append(defs_err)
            defs: dict = {}
        else:
            defs = raw_defs.get("$defs", {}) if isinstance(raw_defs, dict) else {}
        problems.extend(collect_problems(ru, en, defs))
    elif ru_err is None and not isinstance(ru, dict):
        problems.append("ru.json: ожидался объект")
    elif en_err is None and not isinstance(en, dict):
        problems.append("en.json: ожидался объект")
    if problems:
        print("\n".join(problems), file=sys.stderr)  # noqa: T201
        return 1
    count = len(list(walk(ru))) if isinstance(ru, dict) else 0
    print(f"i18n ok: {count} ключей, enum-покрытие {', '.join(ENUM_MAP)}")  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
