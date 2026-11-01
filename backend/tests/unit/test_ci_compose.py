"""CI smoke must never overwrite user state or attach candidate containers to it."""

import copy
import importlib.util
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("ci_compose", ROOT / "scripts/ci_compose.py")
compose = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compose)


@pytest.mark.parametrize("kind", ["file", "symlink", "dangling"])
def test_existing_env_is_untouched(tmp_path, kind):
    path = tmp_path / ".env"
    target = tmp_path / "target"
    if kind == "file":
        path.write_text("private sentinel")
    else:
        if kind == "symlink":
            target.write_text("private sentinel")
        path.symlink_to(target)
    with pytest.raises(FileExistsError), compose.own_env(path):
        pytest.fail("existing env accepted")
    assert os.path.lexists(path)
    if kind != "dangling":
        assert path.read_text() == "private sentinel"


def test_own_env_exclusive_private_and_cleaned_on_failure(tmp_path):
    path = tmp_path / ".env"
    with pytest.raises(RuntimeError), compose.own_env(path):
        assert path.stat().st_mode & 0o777 == 0o600
        assert "LLM_CHAIN=mock" in path.read_text()
        raise RuntimeError("failure")
    assert not path.exists()


def test_replacement_env_is_preserved(tmp_path):
    path = tmp_path / ".env"
    with compose.own_env(path):
        original = tmp_path / "original"
        path.rename(original)
        path.write_text("replacement")
    assert path.read_text() == "replacement"


def candidate_config(root):
    (root / "data").mkdir()
    (root / "data" / "sentinel").write_text("source")
    return {
        "name": "cx-pulse",
        "volumes": {"pgdata": {"name": "cx-pulse_pgdata"}},
        "networks": {"default": {"name": "cx-pulse_default"}},
        "services": {
            "postgres": {
                "ports": ["5432:5432"],
                "volumes": [{"type": "volume", "source": "pgdata", "target": "/var/lib/postgresql/data"}],
            },
            "backend": {
                "image": "cx-pulse-backend:latest",
                "build": {},
                "ports": ["8000:8000"],
                "container_name": "primary",
                "volumes": [{"type": "bind", "source": str(root / "data"), "target": "/data"}],
            },
            "personal": {"ports": ["9999:9999"]},
        },
    }


def test_isolation_copies_bind_data_and_scopes_resources(tmp_path, monkeypatch):
    monkeypatch.setattr(compose, "ROOT", tmp_path)
    config = candidate_config(tmp_path)
    isolated = compose.isolate(
        copy.deepcopy(config), "cx-ci-test", "cx-pulse-backend:ci", 18080, tmp_path / "candidate"
    )
    assert isolated["name"] == "cx-ci-test"
    assert "name" not in isolated["volumes"]["pgdata"]
    assert "name" not in isolated["networks"]["default"]
    assert isolated["services"]["postgres"]["ports"] == []
    assert isolated["services"]["personal"]["ports"] == []
    backend = isolated["services"]["backend"]
    assert "build" not in backend and "container_name" not in backend
    assert backend["image"] == "cx-pulse-backend:ci"
    assert backend["ports"][0]["host_ip"] == "127.0.0.1"
    assert backend["environment"]["LLM_CHAIN"] == "mock"
    copied = Path(backend["volumes"][0]["source"]) / "sentinel"
    copied.write_text("candidate mutation")
    assert (tmp_path / "data" / "sentinel").read_text() == "source"


@pytest.mark.parametrize(
    "violation",
    [
        "external_volume",
        "external_network",
        "outside_bind",
        "privileged",
        "primary_project",
        "primary_image",
        "primary_port",
    ],
)
def test_unsafe_config_rejected(tmp_path, monkeypatch, violation):
    monkeypatch.setattr(compose, "ROOT", tmp_path)
    config = candidate_config(tmp_path)
    project, image, port = "cx-ci-test", "cx-pulse-backend:ci", 18080
    if violation.startswith("external"):
        section = "volumes" if violation == "external_volume" else "networks"
        next(iter(config[section].values()))["external"] = True
    elif violation == "outside_bind":
        config["services"]["backend"]["volumes"][0]["source"] = "/etc"
    elif violation == "privileged":
        config["services"]["backend"]["privileged"] = True
    elif violation == "primary_project":
        project = "cx-pulse"
    elif violation == "primary_image":
        image = "cx-pulse-backend:latest"
    else:
        port = 80
    with pytest.raises(ValueError):
        compose.isolate(config, project, image, port, tmp_path / "candidate")
