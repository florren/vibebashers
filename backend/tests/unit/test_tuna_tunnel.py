"""T-269: dotenv как данные, секрет только в env, управление только своим процессом."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("personal_tuna", ROOT / "scripts/tuna_tunnel.py")
assert spec and spec.loader
tuna = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tuna)


def test_tuna_env_is_not_executable_and_key_never_in_argv(tmp_path: Path, monkeypatch: Any) -> None:
    key = "tak_synthetic_unit_key_not_real"
    envfile = tmp_path / ".env"
    envfile.write_text(f'TUNA_API_KEY="{key}"\nUNRELATED=$(touch SHOULD_NOT_EXIST)\n')
    assert tuna.env_values(envfile) == {"TUNA_API_KEY": key}
    monkeypatch.setattr(sys, "argv", ["tuna_tunnel.py", "start", "--env-file", str(envfile)])
    monkeypatch.setattr(tuna.shutil, "which", lambda _: "/usr/bin/tuna")
    monkeypatch.setattr(tuna, "identity", lambda _: "12345")
    monkeypatch.setattr(tuna, "managed", lambda state: bool(state.get("pid")))

    class Response:
        status = 200

        def __enter__(self) -> Any:
            return self

        def __exit__(self, *args: Any) -> None:
            pass

        def read(self, *args: Any) -> bytes:
            return b'<html><div id="root"></div><script src="/assets/personal-test.js"></script></html>'

    monkeypatch.setattr(tuna.urllib.request, "urlopen", lambda *args, **kwargs: Response())
    calls = []

    def launch(argv: list[str], **kwargs: Any) -> Any:
        assert key not in " ".join(argv)
        assert kwargs["env"]["TUNA_API_KEY"] == key
        assert argv[1:] == [
            "http",
            "9999",
            "--subdomain=royal-penguin-6552",
            "--rate-limit=10",
            "--https-redirect",
            "--inspect=false",
        ]
        calls.append(argv)
        tuna.os.write(
            kwargs["stdout"],
            (json.dumps({"msg": "Forwarding", "url": "https://royal-penguin-6552.a.tuna.free"}) + "\n").encode(),
        )
        return SimpleNamespace(pid=98765)

    monkeypatch.setattr(tuna.subprocess, "Popen", launch)
    assert tuna.main() == 0 and len(calls) == 1
    statefile = tmp_path / ".cx/personal-tunnel/state.json"
    assert key not in statefile.read_text()
    assert statefile.stat().st_mode & 0o777 == 0o600
    assert tuna.main() == 0 and len(calls) == 1  # повторный install не плодит туннели
    assert json.loads(statefile.read_text())["pid"] == 98765


def test_stop_does_not_kill_unmanaged_process(tmp_path: Path, monkeypatch: Any) -> None:
    state = tmp_path / "state.json"
    state.write_text('{"pid":1234,"start":"old"}')
    monkeypatch.setattr(tuna, "managed", lambda _: False)

    def forbidden(*args: Any) -> None:
        raise AssertionError("чужой процесс не должен завершаться")

    monkeypatch.setattr(tuna.os, "kill", forbidden)
    tuna.stop(state)
    assert not state.exists()


def test_forwarding_accepts_only_assigned_tuna_host(tmp_path: Path) -> None:
    path = tmp_path / "log"
    for url in [
        "http://royal-penguin-6552.a.tuna.free",
        "https://royal-penguin-6552.evil.example",
        "https://royal-penguin-6552.a.tuna.free.attacker.test",
        "https://royal-penguin-6552.a.tuna.free:9999",
        "https://other.a.tuna.free",
    ]:
        path.write_text(json.dumps({"msg": "Forwarding", "url": url}) + "\n")
        assert tuna.forwarding_url(path) is None
    path.write_text(json.dumps({"msg": "Forwarding", "url": "https://royal-penguin-6552.a.tuna.free"}) + "\n")
    assert tuna.forwarding_url(path) == "https://royal-penguin-6552.a.tuna.free"
