#!/usr/bin/env python3
"""T-265: построить артефакт из JSONL контрольных исходов и метаданных согласования."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.economics.calibration import fit


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = []
    with args.input.open() as source:
        for line in source:
            if len(rows) >= 100000:
                raise ValueError("Предел набора: 100000 наблюдений")
            if line.strip():
                rows.append(json.loads(line))
    artifact = fit(rows, json.loads(args.metadata.read_text()))
    args.output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
