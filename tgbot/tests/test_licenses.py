"""Отдельный lock не наследует metadata другой версии Pydantic из backend."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("license_gate", ROOT / "scripts/licenses_check.py")
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


def test_bot_inventory_covers_its_own_lock_and_report():
    rows = gate.inventory(ROOT, "tgbot")
    assert {row["ecosystem"] for row in rows} == {"python"}
    assert next(row for row in rows if row["name"] == "aiogram")["license"] == "MIT"
    assert next(row for row in rows if row["name"] == "pydantic")["version"] == "2.13.5"
    assert len(rows) == 36
    assert (ROOT / "tgbot/THIRD_PARTY_LICENSES.md").read_text() == gate.render(rows, "tgbot")


def test_new_bot_version_requires_its_own_metadata(tmp_path):
    (tmp_path / "tgbot").mkdir()
    (tmp_path / "docs/licenses").mkdir(parents=True)
    (tmp_path / "tgbot/uv.lock").write_text(
        '[[package]]\nname="cx-pulse-tgbot"\nversion="0"\n[[package]]\nname="aiogram"\nversion="999"\n'
    )
    (tmp_path / "docs/licenses/tgbot-metadata.json").write_text(json.dumps([]))
    with pytest.raises(ValueError, match="нет проверенных metadata"):
        gate.python_inventory(tmp_path, "tgbot")
