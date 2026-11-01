"""T-152: SPDX разбирается структурно; неизвестные значения не разрешаются."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("license_gate", ROOT / "scripts/licenses_check.py")
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


@pytest.mark.parametrize(
    "expression",
    ["MIT", "LGPL-3.0-only", "(MIT OR CC0-1.0)", "MIT AND (Apache-2.0 OR BSD-2-Clause)", "GPL-3.0-only OR MIT"],
)
def test_allowed_expression(expression):
    assert gate.license_allowed(expression)


@pytest.mark.parametrize("expression", ["GPL-3.0-only", "AGPL-3.0-or-later", "SSPL-1.0", "MIT AND GPL-3.0-only"])
def test_denied_expression(expression):
    assert not gate.license_allowed(expression)


@pytest.mark.parametrize(
    "expression",
    [
        "",
        "MIT OR LicenseRef-Unknown",
        "MIT OR",
        "MIT AND AND MIT",
        "(MIT",
        "MIT)",
        "MIT;Apache-2.0",
        "MIT WITH unknown-exception",
        "LGPL-mystery",
        "SEE LICENSE IN LICENSE.txt",
        "UNLICENSED",
        "BUSL-1.1",
        "SSPL-3.0 OR MIT",
    ],
)
def test_unknown_or_invalid_fails_even_in_unused_branch(expression):
    with pytest.raises(ValueError):
        gate.license_allowed(expression)


def test_inventory_matches_current_lock_and_report():
    rows = gate.inventory(ROOT)
    assert len(rows) > 400
    assert {r["scope"] for r in rows} == {"dev", "runtime"}
    assert "pglast" not in {r["name"] for r in rows}
    assert {r["name"] for r in rows if r["license"] == "LGPL-3.0-only"} == {"psycopg", "psycopg-binary", "psycopg-pool"}
    assert (ROOT / "THIRD_PARTY_LICENSES.md").read_text() == gate.render(rows)


def test_metadata_cannot_override_declared_expression(tmp_path):
    import json
    import shutil

    (tmp_path / "backend").mkdir()
    (tmp_path / "docs/licenses").mkdir(parents=True)
    shutil.copyfile(ROOT / "backend/uv.lock", tmp_path / "backend/uv.lock")
    cache = json.loads((ROOT / "docs/licenses/python-metadata.json").read_text())
    cache[0]["expression"] = "GPL-3.0-only"
    (tmp_path / "docs/licenses/python-metadata.json").write_text(json.dumps(cache))
    with pytest.raises(ValueError, match="противоречит"):
        gate.python_inventory(tmp_path)


def test_new_python_version_needs_metadata(tmp_path):
    (tmp_path / "backend").mkdir()
    (tmp_path / "docs/licenses").mkdir(parents=True)
    (tmp_path / "backend/uv.lock").write_text(
        '[[package]]\nname="cx-pulse-backend"\nversion="0"\n[[package]]\nname="unknown"\nversion="1"\n'
    )
    (tmp_path / "docs/licenses/python-metadata.json").write_text("[]")
    with pytest.raises(ValueError, match="нет проверенных metadata"):
        gate.python_inventory(tmp_path)
