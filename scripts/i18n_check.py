"""Проверка словарей i18n фронта (T-156): валидный JSON, нет пустых строк, ключи enum-значений из common.schema.json покрыты.

Использование: python scripts/i18n_check.py  (exit 1 при проблемах).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RU = ROOT / "frontend/src/shared/i18n/ru.json"
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


def main() -> int:
    problems: list[str] = []
    ru = json.loads(RU.read_text(encoding="utf-8"))
    for key, val in walk(ru):
        if not isinstance(val, str) or not val.strip():
            problems.append(f"пустое значение: {key}")
    defs = json.loads(COMMON.read_text(encoding="utf-8")).get("$defs", {})
    for name, prefix in ENUM_MAP.items():
        enum = defs.get(name, {}).get("enum") or []
        section = get(ru, prefix) or {}
        for code in enum:
            if code not in section:
                problems.append(f"нет перевода {prefix}.{code}")
    if problems:
        print("\n".join(problems), file=sys.stderr)  # noqa: T201
        return 1
    print(f"i18n ok: {len(list(walk(ru)))} ключей, enum-покрытие {', '.join(ENUM_MAP)}")  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
