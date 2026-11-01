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
