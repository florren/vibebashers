"""T-145: CI не теряет тесты, не дублирует их и не скрывает отсутствие runner."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("ci_test_shard", ROOT / "scripts/ci_test_shard.py")
shards = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shards)


def test_collection_uses_actual_pytest_modules():
    output = "tests/unit/test_a.py::test_first\ntests/unit/test_a.py::test_second[x]\ntests/integration/test_b.py::test_db\n2 tests collected\n"
    assert shards.collection_modules(output) == ["tests/integration/test_b.py", "tests/unit/test_a.py"]


@pytest.mark.parametrize("output", ["no tests collected", "tests/../secret.py::test_x", "tests/not_python.sh::test_x"])
def test_invalid_collection_is_failure(output):
    with pytest.raises(ValueError):
        shards.collection_modules(output)


def test_every_module_is_in_exactly_one_runner():
    modules = [f"tests/unit/test_{i:03d}.py" for i in range(100)]
    selected = [shards.partition(modules, index, 4) for index in range(4)]
    assert sorted(path for group in selected for path in group) == modules
    assert all(len(group) == 25 for group in selected)


@pytest.mark.parametrize("index,count", [(-1, 4), (4, 4), (0, 0), (3, 4)])
def test_invalid_or_empty_shard_is_failure(index, count):
    with pytest.raises(ValueError):
        shards.partition(["tests/unit/test_a.py"], index, count)


@pytest.mark.parametrize(
    "mutation",
    [
        None,
        "missing",
        "duplicate",
        "different_collection",
        "lost_module",
        "failed",
        "unfinished",
        "lost_test",
        "different_revision",
    ],
)
def test_aggregate_verifies_complete_manifests(tmp_path, mutation):
    modules = [f"tests/unit/test_{i}.py" for i in range(8)]
    rows = [
        {
            "index": i,
            "count": 4,
            "discovered": modules,
            "selected": shards.partition(modules, i, 4),
            "nodeids": [m + "::test_x" for m in modules],
            "revision": "abc",
            "exit_code": 0,
            "executed_count": 2,
        }
        for i in range(4)
    ]
    if mutation == "missing":
        rows.pop()
    elif mutation == "duplicate":
        rows[3]["index"] = 0
    elif mutation == "different_collection":
        rows[3]["discovered"] = modules[:-1]
    elif mutation == "lost_module":
        rows[3]["selected"].pop()
    elif mutation == "failed":
        rows[3]["exit_code"] = 1
    elif mutation == "unfinished":
        rows[3]["exit_code"] = None
    elif mutation == "lost_test":
        rows[3]["executed_count"] = 1
    elif mutation == "different_revision":
        rows[3]["revision"] = "def"
    paths = []
    for i, row in enumerate(rows):
        path = tmp_path / f"manifest-{i}.json"
        path.write_text(json.dumps(row))
        paths.append(path)
    if mutation:
        with pytest.raises(ValueError):
            shards.verify_manifests(paths, 4)
    else:
        shards.verify_manifests(paths, 4)


@pytest.mark.parametrize("exit_code", [0, 1])
def test_runner_reports_progress_and_preserves_result(tmp_path, monkeypatch, capsys, exit_code):
    """Ошибка выполнения сохраняется в manifest и exit code; прогресс тестов виден."""
    from subprocess import CompletedProcess

    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if "--collect-only" in command:
            return CompletedProcess(command, 0, stdout="tests/unit/test_a.py::test_x\n", stderr="")
        junit = Path(next(arg.split("=", 1)[1] for arg in command if arg.startswith("--junitxml=")))
        junit.write_text('<testsuites><testsuite><testcase name="test_x"/></testsuite></testsuites>')
        return CompletedProcess(command, exit_code)

    monkeypatch.setattr(shards.subprocess, "run", run)
    monkeypatch.setattr(shards.subprocess, "check_output", lambda *args, **kwargs: "abc\n")
    assert shards.main(["--index", "0", "--count", "1", "--manifest-dir", str(tmp_path)]) == exit_code
    row = json.loads((tmp_path / "manifest-0.json").read_text())
    assert row["exit_code"] == exit_code
    assert row["executed_count"] == 1
    assert row["selected"] == ["tests/unit/test_a.py"]
    assert "-u" in calls[1] and "-vv" in calls[1]
    output = capsys.readouterr().out
    assert "Collecting complete pytest suite" in output
    assert "running 1 tests in 1 modules" in output
    assert f"exit_code={exit_code}, executed=1/1" in output


@pytest.mark.parametrize(
    "mode", ["pass", "fail", "timeout", "fail_timeout", "soft_async", "soft_clock", "capsys", "capfd", "path_open"]
)
def test_real_child_diagnostics_preserve_success_failure_and_bound_teardown(tmp_path, monkeypatch, mode):
    """Настоящий child сохраняет exit status; зависший teardown не становится зелёным manifest."""
    import os
    import shutil
    import subprocess

    checkout = tmp_path / "checkout"
    (checkout / "scripts").mkdir(parents=True)
    (checkout / "backend/tests").mkdir(parents=True)
    shutil.copyfile(ROOT / "scripts/ci_test_shard.py", checkout / "scripts/ci_test_shard.py")
    bodies = {
        "pass": "def test_sample():\n    assert True\n",
        "fail": "def test_sample():\n    assert False\n",
        "timeout": "import time, pytest\n@pytest.fixture\ndef waiting():\n    yield\n    time.sleep(10)\ndef test_sample(waiting):\n    assert True\n",
        "fail_timeout": "import time, pytest\n@pytest.fixture\ndef waiting():\n    yield\n    time.sleep(10)\ndef test_sample(waiting):\n    assert False\n",
        "capsys": "def test_sample(capsys):\n    assert capsys.readouterr().err == ''\n",
        "capfd": "def test_sample(capfd):\n    assert capfd.readouterr().err == ''\n",
        "path_open": "from pathlib import Path\ndef test_sample(monkeypatch):\n    def forbidden(*args, **kwargs):\n        raise AssertionError('unexpected Path.open during test')\n    monkeypatch.setattr(Path, 'open', forbidden)\n",
        "soft_async": "import asyncio, pytest\n@pytest.mark.asyncio\nasync def test_sample():\n    local_secret = 'DO_NOT_LOG_FRAME_LOCALS_784129'\n    await asyncio.sleep(0.3)\n    assert local_secret\n",
        "soft_clock": "import time\ndef test_sample(monkeypatch):\n    monkeypatch.setattr(time, 'monotonic', lambda: 0.0)\n    time.sleep(0.3)\n",
    }
    (checkout / "backend/tests/test_sample.py").write_text(bodies[mode])
    actual_run = subprocess.run

    def run(command, **kwargs):
        if "--collect-only" not in command:
            command = [
                ("faulthandler_timeout=0.5" if mode in {"timeout", "fail_timeout"} else "faulthandler_timeout=5")
                if value == "faulthandler_timeout=300"
                else value
                for value in command
            ]
            command += ["-o", "ci_phase_dump_seconds=0.05"]
            kwargs.update(stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=15)
        return actual_run(command, **kwargs)

    monkeypatch.setattr(shards, "ROOT", checkout)
    monkeypatch.setattr(shards.subprocess, "run", run)
    monkeypatch.setattr(shards.subprocess, "check_output", lambda *args, **kwargs: "abc\n")
    # PYTHONPATH child содержит только собственную копию plugin; реальные ключи не нужны.
    monkeypatch.setenv("PYTHONPATH", str(checkout) + os.pathsep + os.environ.get("PYTHONPATH", ""))
    output = tmp_path / "results"
    code = shards.main(["--index", "0", "--count", "1", "--manifest-dir", str(output)])
    row = json.loads((output / "manifest-0.json").read_text())
    assert row["exit_code"] == code
    assert row["selected"] == ["tests/test_sample.py"]
    phases = [json.loads(line) for line in (output / "phases-0.jsonl").read_text().splitlines()]
    assert any(phase["phase"] == "setup" and phase["state"] == "started" for phase in phases)
    assert any(phase["phase"] == "call" and phase["state"] == "finished" for phase in phases)
    if mode in {"fail", "timeout", "fail_timeout"}:
        assert code != 0
        with pytest.raises(ValueError):
            shards.verify_manifests([output / "manifest-0.json"], 1)
        if mode in {"timeout", "fail_timeout"}:
            assert any(p["phase"] == "teardown" and p["state"] == "started" for p in phases)
            assert not any(p["phase"] == "teardown" and p["state"] == "finished" for p in phases)
    else:
        assert code == 0 and row["executed_count"] == 1
        shards.verify_manifests([output / "manifest-0.json"], 1)
    if mode.startswith("soft_"):
        assert any(p["state"] == "waiting" and p["seconds"] > 0 for p in phases)
        stacks = (output / "phases-0.stacks.log").read_text()
        assert "watch" in stacks
        if mode == "soft_async":
            assert "[ci-tasks]" in stacks and "test_sample" in stacks
            assert "DO_NOT_LOG_FRAME_LOCALS_784129" not in stacks


def test_aggregate_cli_requires_only_stdlib(tmp_path):
    """Даже aggregate Python -S не импортирует pytest и не запускает observer."""
    import subprocess
    import sys

    manifest = {
        "index": 0,
        "count": 1,
        "discovered": ["tests/test_sample.py"],
        "selected": ["tests/test_sample.py"],
        "nodeids": ["tests/test_sample.py::test_sample"],
        "revision": "abc",
        "exit_code": 0,
        "executed_count": 1,
    }
    (tmp_path / "manifest-0.json").write_text(json.dumps(manifest))
    result = subprocess.run(
        [sys.executable, "-S", str(ROOT / "scripts/ci_test_shard.py"), "--verify", str(tmp_path), "--count", "1"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert "ci-phase" not in result.stdout + result.stderr
