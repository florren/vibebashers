"""Сетевой retry относится только к установке инструмента, не к результатам тестов."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]


def test_uv_retry_is_bounded_and_last_failure_is_fatal():
    action = yaml.load((ROOT / ".github/actions/setup-uv/action.yml").read_text(), Loader=yaml.BaseLoader)
    assert action["inputs"]["version"]["default"] == "0.13.7"
    first, retry = action["runs"]["steps"]
    assert first["uses"] == retry["uses"] == "astral-sh/setup-uv@v5"
    assert first["id"] == "install" and first["continue-on-error"] == "true"
    assert retry["if"] == "steps.install.outcome == 'failure'"
    assert "continue-on-error" not in retry
    assert first["with"]["version"] == retry["with"]["version"] == "${{ inputs.version }}"


def test_all_uv_consumers_use_retry_after_checkout():
    workflow = yaml.load((ROOT / ".github/workflows/ci.yml").read_text(), Loader=yaml.BaseLoader)
    for name in ("contracts", "db", "lint", "backend-tests", "frontend-tests"):
        steps = workflow["jobs"][name]["steps"]
        setup = next(i for i, step in enumerate(steps) if step.get("uses") == "./.github/actions/setup-uv")
        assert any(step.get("uses") == "actions/checkout@v4" for step in steps[:setup])
        assert "continue-on-error" not in steps[setup]
