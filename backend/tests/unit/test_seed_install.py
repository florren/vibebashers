"""T-270: установщик не скрывает ошибку сида; версии pg-tools проверяются до записи."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.sim import baseline

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize(
    "dump,restore,server,ok", [(16, 16, 160006, True), (15, 16, 160006, False), (16, 17, 160006, False)]
)
def test_baseline_tool_versions(monkeypatch, dump, restore, server, ok):
    monkeypatch.setattr(baseline.shutil, "which", lambda name: f"/usr/bin/{name}")

    def version(cmd, **kwargs):
        return SimpleNamespace(
            returncode=0, stdout=f"{cmd[0]} (PostgreSQL) {dump if 'pg_dump' in cmd[0] else restore}.6", stderr=""
        )

    monkeypatch.setattr(baseline.subprocess, "run", version)
    if ok:
        assert baseline.check_tools(server) == {"server": 16, "pg_dump": 16, "pg_restore": 16}
    else:
        with pytest.raises(baseline.BaselineToolingError, match="major 16"):
            baseline.check_tools(server)


def test_baseline_missing_or_unreadable_tool(monkeypatch):
    monkeypatch.setattr(baseline.shutil, "which", lambda name: None)
    with pytest.raises(baseline.BaselineToolingError, match="pg_dump не найден"):
        baseline.check_tools(160006)
    monkeypatch.setattr(baseline.shutil, "which", lambda name: name)
    monkeypatch.setattr(baseline.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=1, stdout=""))
    with pytest.raises(baseline.BaselineToolingError, match="определить"):
        baseline.check_tools(160006)


@pytest.mark.parametrize("status", [2, 3, 4])
def test_installer_stops_on_seed_error(tmp_path, status):
    script = tmp_path / "install.sh"
    script.write_bytes((ROOT / "install.sh").read_bytes())
    (tmp_path / ".env").write_text("PROFILE=lite\n")
    binpath = tmp_path / "bin"
    binpath.mkdir()
    docker = binpath / "docker"
    docker.write_text(f"""#!/usr/bin/env bash
if [[ "$*" == *"exec -T backend python /scripts/seed/run.py"* ]]; then
  [[ "$*" == *"--if-needed"* ]] || exit 99
  exit {status}
fi
exit 0
""")
    docker.chmod(0o755)
    for name, body in [("ss", "exit 0"), ("curl", 'printf "{\\"status\\":\\"ok\\"}\\n"')]:
        p = binpath / name
        p.write_text("#!/usr/bin/env bash\n" + body + "\n")
        p.chmod(0o755)
    result = subprocess.run(
        ["bash", str(script), "--no-stt"],
        env={**os.environ, "PATH": str(binpath) + os.pathsep + os.environ["PATH"]},
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert f"кодом {status}" in result.stderr
    assert "сид ещё не реализован" not in result.stdout
    assert "Анонимный чат:" not in result.stdout
