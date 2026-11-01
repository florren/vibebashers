"""Layer checks include the index, even when the worktree has no unstaged diff."""

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("check_owners", ROOT / "scripts/check_owners.py")
owners = importlib.util.module_from_spec(spec)
spec.loader.exec_module(owners)


def test_staged_cross_layer_change_is_rejected(tmp_path, monkeypatch, capsys):
    def git(*args):
        subprocess.run(["git", *args], cwd=tmp_path, capture_output=True, check=True)

    git("init", "-b", "main")
    (tmp_path / "CODEOWNERS").write_text("/CODEOWNERS @layer-l5\n/scripts/ @layer-l5\n/backend/ @layer-l3\n")
    (tmp_path / "backend").mkdir()
    changed = tmp_path / "backend/app.py"
    changed.write_text("original")
    git("add", ".")
    git("-c", "user.name=CI fixture", "-c", "user.email=ci@example.invalid", "commit", "-m", "fixture")
    changed.write_text("staged change")
    git("add", "backend/app.py")
    monkeypatch.setattr(owners, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["check_owners.py", "--layer", "L5"])
    assert owners.main() == 1
    assert "backend/app.py" in capsys.readouterr().out
    monkeypatch.setattr(sys, "argv", ["check_owners.py", "--layer", "L5", "--allow-cross"])
    assert owners.main() == 0
