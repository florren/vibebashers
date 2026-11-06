"""Установщик перечитывает первичный seed до объявления готовности."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


def install(tmp_path: Path, case: str):
    shutil.copyfile(ROOT / "install.sh", tmp_path / "install.sh")
    (tmp_path / ".env").write_text("PROFILE=lite\n")
    programs = tmp_path / "bin"
    programs.mkdir()
    log = tmp_path / "commands.jsonl"
    (programs / "docker").write_text(
        f"#!{sys.executable}\n"
        + """import json,os,sys
from pathlib import Path
args=sys.argv[1:];case=os.environ['CASE'];marker=Path(os.environ['MARKER'])
with open(os.environ['LOG'],'a') as f:f.write(json.dumps(['docker',*args])+'\\n')
if '/scripts/seed/run.py' in args:sys.exit(2 if case=='seed_fail' else 0)
if '/scripts/install_seed_state.py' in args:
 if case in ('active','helper_fail'):sys.exit(2)
 if case=='same':sys.exit(0)
 sys.exit(3 if not marker.exists() or case=='still_stale' else 0)
if 'restart' in args:
 if case=='restart_fail':sys.exit(7)
 marker.touch()
"""
    )
    (programs / "curl").write_text(
        f"#!{sys.executable}\n"
        + """import json,os,sys
from pathlib import Path
with open(os.environ['LOG'],'a') as f:f.write(json.dumps(['curl',*sys.argv[1:]])+'\\n')
if os.environ['CASE']=='health_fail' and Path(os.environ['MARKER']).exists():sys.exit(22)
print('{"status":"ok"}')
"""
    )
    (programs / "python3").write_text(
        "#!/usr/bin/env bash\n"
        'if [ "$1" = scripts/tuna_tunnel.py ]; then exit 0; fi\n'
        'if [ "$1" = -c ] && [ "$2" = "import qrcode" ]; then exit 1; fi\n' + f'exec "{sys.executable}" "$@"\n'
    )
    for name in ("ss", "sleep"):
        (programs / name).write_text("#!/usr/bin/env bash\nexit 0\n")
    for program in programs.iterdir():
        program.chmod(0o755)
    result = subprocess.run(
        ["bash", str(tmp_path / "install.sh"), "--no-stt"],
        env={
            **os.environ,
            "PATH": str(programs) + os.pathsep + os.environ["PATH"],
            "CASE": case,
            "MARKER": str(tmp_path / "restarted"),
            "LOG": str(log),
        },
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result, [json.loads(line) for line in log.read_text().splitlines()]


def test_first_seed_restarts_then_checks_health_and_pointer_before_success(tmp_path: Path):
    result, calls = install(tmp_path, "fresh")
    assert result.returncode == 0, result.stderr
    seed = next(i for i, c in enumerate(calls) if "/scripts/seed/run.py" in c)
    checks = [i for i, c in enumerate(calls) if "/scripts/install_seed_state.py" in c]
    restart = next(i for i, c in enumerate(calls) if "restart" in c)
    assert len(checks) == 2 and seed < checks[0] < restart < checks[1]
    assert calls[restart] == ["docker", "compose", "restart", "--no-deps", "--timeout", "120", "backend"]
    assert any(c[0] == "curl" for c in calls[restart + 1 : checks[1]])
    assert "Анонимный чат:" in result.stdout


def test_existing_matching_run_does_not_restart(tmp_path: Path):
    result, calls = install(tmp_path, "same")
    assert result.returncode == 0, result.stderr
    assert any("/scripts/install_seed_state.py" in c for c in calls)
    assert not any("restart" in c for c in calls)


@pytest.mark.parametrize("case", ["seed_fail", "active", "helper_fail", "restart_fail", "health_fail", "still_stale"])
def test_post_seed_failure_never_reports_ready(tmp_path: Path, case: str):
    result, calls = install(tmp_path, case)
    assert result.returncode != 0
    assert "Интерфейс:" not in result.stdout and "Анонимный чат:" not in result.stdout
    if case == "seed_fail":
        assert not any("/scripts/install_seed_state.py" in c for c in calls)
    if case in ("seed_fail", "active", "helper_fail"):
        assert not any("restart" in c for c in calls)
    else:
        assert sum("restart" in c for c in calls) == 1


def state_helper():
    spec = importlib.util.spec_from_file_location("install_seed_state", ROOT / "scripts/install_seed_state.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "memory,row,expected",
    [
        ({"current_run_id": None, "running": False}, (1, False, "baseline", "completed", False, False), 3),
        ({"current_run_id": 1, "running": False}, (1, False, "baseline", "completed", False, False), 0),
        ({"current_run_id": 2, "running": True}, (2, True, "free", "running", True, True), 0),
    ],
)
def test_pointer_decision_preserves_matching_active_world(memory, row, expected):
    assert state_helper().decision(memory, row) == expected


@pytest.mark.parametrize(
    "memory,row",
    [
        ({"running": False}, (1, False, "baseline", "completed", False, False)),
        ({"current_run_id": True, "running": False}, (1, False, "baseline", "completed", False, False)),
        ({"current_run_id": None}, (1, False, "baseline", "completed", False, False)),
        ({"current_run_id": None, "running": False}, None),
        ({"current_run_id": None, "running": False}, (None, False, None, None, False, False)),
        ({"current_run_id": None, "running": False}, (1, True, "baseline", "completed", False, False)),
        ({"current_run_id": None, "running": False}, (1, False, "free", "stopped", False, False)),
        ({"current_run_id": None, "running": False}, (1, False, "baseline", "completed", True, False)),
        ({"current_run_id": None, "running": False}, (1, False, "baseline", "completed", False, True)),
        ({"current_run_id": 7, "running": False}, (1, False, "baseline", "completed", False, False)),
    ],
)
def test_pointer_decision_rejects_unsafe_or_malformed_reload(memory, row):
    helper = state_helper()
    with pytest.raises(helper.InstallStateError):
        helper.decision(memory, row)


def test_reload_health_deadline_bounds_nonresponsive_local_server(tmp_path: Path):
    import http.server
    import shlex
    import threading
    import time

    if shutil.which("curl") is None:
        pytest.skip("curl отсутствует в окружении unit-теста")
    release = threading.Event()

    class SilentHealth(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            release.wait(5)

        def log_message(self, *_args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), SilentHealth)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        source = (ROOT / "install.sh").read_text().split("wait_backend_after_seed() {", 1)[1].split("\n}\n", 1)[0]
        url = f"http://127.0.0.1:{server.server_port}/api/health"
        assert server.server_port not in (8000, 9999, 5432)
        script = "set -e\nwait_backend_after_seed() {" + source + "\n}\n"
        script += "wait_backend_after_seed 1 " + shlex.quote(url) + "\nprintf 'UNEXPECTED_READY'\n"
        started = time.monotonic()
        result = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=5)
        assert result.returncode != 0 and "UNEXPECTED_READY" not in result.stdout
        assert time.monotonic() - started < 4
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
