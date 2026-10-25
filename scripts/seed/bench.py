"""Проверка золотого lite-набора (T-021): python scripts/seed/bench.py --check."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LITE = ROOT / "data" / "golden" / "lite_v1.jsonl"
REQUIRED = ("signal_type", "product", "system", "criticality", "complexity", "team", "flags", "needs_hitl")


def check(path: Path = LITE) -> list[str]:
    errors: list[str] = []
    if not path.is_file():
        return [f"нет файла {path}"]
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not 30 <= len(rows) <= 40:
        errors.append(f"кейсов {len(rows)}, ожидается 30–40")
    for i, row in enumerate(rows, start=1):
        gold = row.get("gold") or {}
        missing = [k for k in REQUIRED if k not in gold]
        if missing:
            errors.append(f"строка {i}: нет {missing}")
        if "ambiguous" in (row.get("tags") or []):
            errors.append(f"строка {i}: ambiguous не входит в lite")
    return errors


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    if not args.check:
        ap.error("укажите --check")
    errors = check()
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(f"ok {LITE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
