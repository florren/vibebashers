"""Сетевой retry относится только к установке инструмента, не к результатам тестов."""

import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]


def test_uv_retry_is_bounded_and_last_failure_is_fatal():
    action = yaml.load((ROOT / ".github/actions/setup-uv/action.yml").read_text(), Loader=yaml.BaseLoader)
    assert action["inputs"]["version"]["default"] == "0.13.7"
    first, retry = action["runs"]["steps"]
    assert first["uses"] == "astral-sh/setup-uv@v5"
    assert first["id"] == "install" and first["continue-on-error"] == "true"
    assert retry["if"] == "steps.install.outcome == 'failure'"
    assert "continue-on-error" not in retry
    assert first["with"]["version"] == retry["env"]["UV_VERSION"] == "${{ inputs.version }}"
    assert "sha256sum --check --status" in retry["run"]
    assert "--proto '=https' --tlsv1.2" in retry["run"]


@pytest.mark.parametrize("failure", ["network", "checksum"])
def test_pypi_fallback_failure_cannot_publish_unverified_binary(tmp_path, failure):
    action = yaml.load((ROOT / ".github/actions/setup-uv/action.yml").read_text(), Loader=yaml.BaseLoader)
    script = action["runs"]["steps"][1]["run"]
    tools = tmp_path / "tools"
    tools.mkdir()
    curl = tools / "curl"
    curl.write_text(
        "#!/bin/bash\nexit 22\n"
        if failure == "network"
        else '#!/bin/bash\nwhile [ "$#" -gt 0 ]; do\n'
        'if [ "$1" = "--output" ]; then echo corrupt > "$2"; exit 0; fi\nshift\ndone\nexit 1\n'
    )
    curl.chmod(0o755)
    github_path = tmp_path / "github-path"
    github_path.touch()
    result = subprocess.run(
        ["bash", "-c", script],
        env={
            **os.environ,
            "PATH": f"{tools}:{os.environ['PATH']}",
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_PATH": str(github_path),
            "UV_VERSION": "0.13.7",
        },
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert github_path.read_text() == ""
    assert not list(tmp_path.glob("uv-bootstrap.*/uv"))


def test_all_uv_consumers_use_retry_after_checkout():
    workflow = yaml.load((ROOT / ".github/workflows/ci.yml").read_text(), Loader=yaml.BaseLoader)
    for name in ("contracts", "db", "lint", "backend-tests", "frontend-tests"):
        steps = workflow["jobs"][name]["steps"]
        setup = next(i for i, step in enumerate(steps) if step.get("uses") == "./.github/actions/setup-uv")
        assert any(step.get("uses") == "actions/checkout@v4" for step in steps[:setup])
        assert "continue-on-error" not in steps[setup]
