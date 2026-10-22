"""Сгенерированные файлы совпадают с контрактами (T-006): забытый make sync-contracts = красный тест."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_enums_match_common_schema(tmp_path) -> None:
    current = (ROOT / "backend/app/contracts/enums.py").read_text(encoding="utf-8")
    subprocess.run([sys.executable, str(ROOT / "scripts/gen_enums.py")], check=True, capture_output=True)
    assert (ROOT / "backend/app/contracts/enums.py").read_text(encoding="utf-8") == current, (
        "запустите make sync-contracts"
    )
    from app.contracts.enums import ALL_ENUMS, Sentiment

    defs = json.loads((ROOT / "contracts/events/common.schema.json").read_text(encoding="utf-8"))["$defs"]
    assert set(Sentiment) == set(defs["sentiment"]["enum"])
    assert len(ALL_ENUMS) == sum(1 for d in defs.values() if "enum" in d)


def test_schema_copy_is_fresh() -> None:
    src = (ROOT / "contracts/db/schema.sql").read_text(encoding="utf-8")
    copy = ROOT / "backend/schema.sql"
    assert copy.exists() and copy.read_text(encoding="utf-8") == src, "backend/schema.sql отстал: make sync-contracts"
