"""Установщик различает свои service/port и посторонний занятый порт."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize(
    "services,published,ps_status,port_status,network_mode,listener_status,allowed",
    [
        ("backend", "127.0.0.1:8000", 0, 0, "bridge", 1, True),
        ("backend", "[::]:8000", 0, 0, "bridge", 1, True),
        ("postgres\nbackend\npersonal", "0.0.0.0:8000", 0, 0, "bridge", 1, True),
        ("cx-pulse-foreign", "127.0.0.1:8000", 0, 0, "bridge", 1, False),
        ("personal", "127.0.0.1:8000", 0, 0, "bridge", 1, False),
        ("", "127.0.0.1:8000", 0, 0, "bridge", 1, False),
        ("backend", "127.0.0.1:18000", 0, 0, "bridge", 1, False),
        ("backend", "127.0.0.1:8000", 1, 0, "bridge", 1, False),
        ("backend", "127.0.0.1:8000", 0, 1, "bridge", 1, False),
        ("backend", "", 0, 0, "host|", 0, True),
        ("backend", "", 0, 0, "host|", 1, False),
        ("backend", "", 0, 0, "bridge", 0, False),
        ("cx-pulse-foreign", "", 0, 0, "host|", 0, False),
        ("backend", "", 1, 0, "host|", 0, False),
        ("backend", "", 0, 0, "", 0, False),
        ("backend", "", 0, 0, "host|private", 0, True),
        ("backend", "", 0, 0, "host|host", 0, False),
        ("backend", "", 0, 0, "host|container:other", 0, False),
    ],
)
def test_installer_occupied_port_belongs_to_running_service(
    tmp_path, services, published, ps_status, port_status, network_mode, listener_status, allowed
):
    script = tmp_path / "install.sh"
    script.write_bytes((ROOT / "install.sh").read_bytes())
    (tmp_path / ".env").write_text("PROFILE=lite\n")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/install_host_port.py").write_bytes((ROOT / "scripts/install_host_port.py").read_bytes())
    binpath = tmp_path / "bin"
    binpath.mkdir()
    programs = {
        "ss": "printf 'LISTEN 0 128 127.0.0.1:8000 0.0.0.0:*\\n'",
        "curl": 'printf \'{"status":"ok"}\\n\'',
        "docker": """case "$*" in
  'compose ps --status running --services')
    printf '%s\\n' "$TEST_SERVICES"; exit "$TEST_PS_STATUS" ;;
  'compose port backend 8000')
    printf '%s\\n' "$TEST_PUBLISHED"; exit "$TEST_PORT_STATUS" ;;
  'compose ps --status running --quiet backend') printf '%064d\\n' 1 ;;
  'inspect --format {{.HostConfig.NetworkMode}}|{{.HostConfig.PidMode}} '*) printf '%s\\n' "$TEST_NETWORK_MODE" ;;
  'compose exec -T backend python - 8000') cat >/dev/null; exit "$TEST_LISTENER_STATUS" ;;
  *'exec -T backend python /scripts/seed/run.py'*) exit 77 ;;
esac
exit 0""",
    }
    for name, body in programs.items():
        path = binpath / name
        path.write_text("#!/usr/bin/env bash\n" + body + "\n")
        path.chmod(0o755)
    result = subprocess.run(
        ["bash", str(script), "--no-stt"],
        env={
            **os.environ,
            "PATH": str(binpath) + os.pathsep + os.environ["PATH"],
            "TEST_SERVICES": services,
            "TEST_PUBLISHED": published,
            "TEST_PS_STATUS": str(ps_status),
            "TEST_PORT_STATUS": str(port_status),
            "TEST_NETWORK_MODE": network_mode,
            "TEST_LISTENER_STATUS": str(listener_status),
            "COMPOSE_PROJECT_NAME": "custom-install-project",
        },
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode != 0
    if allowed:
        assert "кодом 77" in result.stderr  # Допущен до seed, который намеренно прерван.
        assert "Порт 8000 занят" not in result.stderr
    else:
        assert "Порт 8000 занят другим процессом" in result.stderr
        assert "сид данных" not in result.stdout
