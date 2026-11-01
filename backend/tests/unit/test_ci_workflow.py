"""Защищённый tests check явно отвергает skipped/failed prerequisites."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("result", ["success", "failure", "cancelled", "skipped"])
def test_required_check_propagates_dependency_results(result):
    workflow = yaml.load((ROOT / ".github/workflows/ci.yml").read_text(), Loader=yaml.BaseLoader)
    aggregate = workflow["jobs"]["tests"]
    assert aggregate["name"] == "tests"
    assert aggregate["if"] == "always()"
    assert set(aggregate["needs"]) == {
        "contracts",
        "db",
        "owners",
        "lint",
        "backend-tests",
        "frontend-tests",
        "build-images",
        "e2e-smoke",
    }
    step = next(step for step in aggregate["steps"] if "NEEDS_JSON" in step.get("env", {}))
    code = step["run"].split("<<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
    results = {name: {"result": "success"} for name in aggregate["needs"]}
    results["backend-tests"]["result"] = result
    completed = subprocess.run(
        [sys.executable, "-c", code],
        env={**os.environ, "NEEDS_JSON": json.dumps(results), "GITHUB_EVENT_NAME": "pull_request"},
        capture_output=True,
        check=False,
    )
    assert (completed.returncode == 0) == (result == "success")


def test_full_suite_and_isolated_runner_contract():
    workflow = yaml.load((ROOT / ".github/workflows/ci.yml").read_text(), Loader=yaml.BaseLoader)
    backend = workflow["jobs"]["backend-tests"]
    assert backend["strategy"]["matrix"]["shard"] == ["0", "1", "2", "3"]
    assert backend["strategy"]["fail-fast"] == "false"
    assert backend["services"]["postgres"]["image"] == "postgres:16"
    assert any("ci_test_shard.py" in step.get("run", "") for step in backend["steps"])
    assert "pip install" not in (ROOT / ".github/workflows/ci.yml").read_text()
    assert "npm run typecheck" in (ROOT / ".github/workflows/ci.yml").read_text()


@pytest.mark.parametrize("event,allowed", [("pull_request", False), ("push", True), ("schedule", True)])
def test_owners_skip_is_only_allowed_outside_pr(event, allowed):
    workflow = yaml.load((ROOT / ".github/workflows/ci.yml").read_text(), Loader=yaml.BaseLoader)
    aggregate = workflow["jobs"]["tests"]
    step = next(step for step in aggregate["steps"] if "NEEDS_JSON" in step.get("env", {}))
    code = step["run"].split("<<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
    results = {name: {"result": "success"} for name in aggregate["needs"]}
    results["owners"]["result"] = "skipped"
    completed = subprocess.run(
        [sys.executable, "-c", code],
        env={**os.environ, "NEEDS_JSON": json.dumps(results), "GITHUB_EVENT_NAME": event},
        capture_output=True,
        check=False,
    )
    assert (completed.returncode == 0) == allowed
