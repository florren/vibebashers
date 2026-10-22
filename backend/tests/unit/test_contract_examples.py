"""Все `examples` из contracts/events/**.schema.json проходят через сгенерированные Pydantic-модели (T-006/T-200/T-221)."""

from __future__ import annotations

import importlib
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCHEMAS = sorted((ROOT / "contracts/events").rglob("*.schema.json"))


def pascal(s: str) -> str:
    return "".join(w.capitalize() for w in re.split(r"[_\-]+", s))


def model_for(path: Path):
    fam = path.parent.name if path.parent != ROOT / "contracts/events" else "root"
    stem = path.name.replace(".schema.json", "")
    mod = importlib.import_module(f"app.contracts.events.{fam}.{stem}")
    defs = json.loads((ROOT / "contracts/events/common.schema.json").read_text(encoding="utf-8"))["$defs"]
    return getattr(mod, pascal(stem) + ("Event" if stem in defs else ""))


@pytest.mark.parametrize("path", SCHEMAS, ids=[str(p.relative_to(ROOT / "contracts/events")) for p in SCHEMAS])
def test_examples_validate(path: Path) -> None:
    schema = json.loads(path.read_text(encoding="utf-8"))
    examples = schema.get("examples") or []
    if not examples:
        pytest.skip("нет examples")
    model = model_for(path)
    for ex in examples:
        model.model_validate(ex)


def test_generated_schemas_are_fresh() -> None:
    import subprocess
    import sys

    before = {p: p.read_text(encoding="utf-8") for p in (ROOT / "backend/app/contracts/events").rglob("*.py")}
    subprocess.run([sys.executable, str(ROOT / "scripts/gen_schemas.py")], check=True, capture_output=True)
    after = {p: p.read_text(encoding="utf-8") for p in (ROOT / "backend/app/contracts/events").rglob("*.py")}
    assert before == after, "backend/app/contracts/events отстал от contracts/events: make sync-contracts"
