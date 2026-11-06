"""Cached restart не зависит от сети и не запускает установку или очистку данных."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
IDS = {"postgres": "1" * 64, "backend": "2" * 64, "personal": "3" * 64, "oneoff": "4" * 64}


def run_restart(tmp_path: Path, case: str = "healthy", flags: tuple[str, ...] = ()):
    shutil.copyfile(ROOT / "install.sh", tmp_path / "install.sh")
    (tmp_path / "scripts").mkdir()
    shutil.copyfile(ROOT / "scripts/install_restart.py", tmp_path / "scripts/install_restart.py")
    envfile = tmp_path / ".env"
    original = b"PROFILE=demo\nAPP_SECRET=synthetic-do-not-print\n"
    envfile.write_bytes(original)
    envfile.chmod(0o600)
    tools = tmp_path / "bin"
    tools.mkdir()
    log = tmp_path / "commands.jsonl"
    (tools / "docker").write_text(
        f"#!{sys.executable}\n"
        + """import json,os,sys
args=sys.argv[1:];case=os.environ['CASE'];ids=json.loads(os.environ['IDS'])
with open(os.environ['CALLS'],'a') as f:f.write(json.dumps(args)+'\\n')
if 'build' in args or 'pull' in args:print('network unavailable',file=sys.stderr);sys.exit(99)
if args[:2]==['compose','ps']:
 service=args[-1]
 if case=='missing' and service=='backend':sys.exit(0)
 print(ids[service])
 if case=='oneoff' and service=='backend':print(ids['oneoff'])
elif args[:1]==['inspect']:
 cid=args[-1];service=next(k for k,v in ids.items() if v==cid)
 if '.Config.Labels' in args[2]:
  print(json.dumps({'com.docker.compose.project':'cached-test','com.docker.compose.service':'backend' if service=='oneoff' else service,'com.docker.compose.oneoff':'True' if service=='oneoff' else 'False'}))
 elif '.State.Health' in args[2]:print('healthy')
 else:print(json.dumps({'image':'sha256:'+('a' if service=='postgres' else 'b')*64,'running':not(case=='stopped' and service=='postgres'),'healthcheck':{'Test':['CMD','pg_isready']}}))
elif args[:2]==['image','inspect']:
 if case=='missing_image' and args[-1].endswith('b'*64):sys.exit(1)
 print(args[-1])
"""
    )
    (tools / "curl").write_text(
        f"#!{sys.executable}\nimport json,os,sys\nwith open(os.environ['CALLS'],'a') as f:f.write(json.dumps(['curl',*sys.argv[1:]])+'\\n')\n"
        + "print(json.dumps({'status':'ok','db':True}))\n"
    )
    for tool in tools.iterdir():
        tool.chmod(0o755)
    result = subprocess.run(
        ["bash", str(tmp_path / "install.sh"), "--restart", *flags],
        env={
            **os.environ,
            "PATH": str(tools) + os.pathsep + os.environ["PATH"],
            "CASE": case,
            "IDS": json.dumps(IDS),
            "CALLS": str(log),
        },
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert envfile.read_bytes() == original and stat.S_IMODE(envfile.stat().st_mode) == 0o600
    assert "synthetic-do-not-print" not in result.stdout + result.stderr
    return result, [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


@pytest.mark.parametrize("case", ["healthy", "stopped", "oneoff"])
def test_network_unavailable_restart_uses_only_existing_resources(tmp_path: Path, case: str):
    result, calls = run_restart(tmp_path, case)
    assert result.returncode == 0, result.stderr
    assert not any(
        set(c) & {"build", "pull", "down", "up", "rm", "create", "run", "exec", "seed", "Tuna", "stt_model.py"}
        for c in calls
    )
    restarts = [c for c in calls if c[0] == "restart"]
    assert restarts == [["restart", "--time", "120", IDS["backend"], IDS["personal"]]]
    assert not any(IDS["oneoff"] in c for c in restarts)
    starts = [c for c in calls if c[0] == "start"]
    assert starts == ([["start", IDS["postgres"]]] if case == "stopped" else [])
    image_checks = [i for i, c in enumerate(calls) if c[:2] == ["image", "inspect"]]
    first_action = next(i for i, c in enumerate(calls) if c[0] in ("start", "restart"))
    assert len(image_checks) == 3 and max(image_checks) < first_action
    curl = [c for c in calls if c[0] == "curl"]
    assert len(curl) == 2 and all(c[1:3] == ["--noproxy", "*"] for c in curl)


@pytest.mark.parametrize("case", ["missing", "missing_image"])
def test_restart_validation_failure_has_no_mutating_actions(tmp_path: Path, case: str):
    result, calls = run_restart(tmp_path, case)
    assert result.returncode != 0
    assert not any(c[0] in ("start", "restart", "run", "create", "rm") for c in calls)
    assert not any("pull" in c or "build" in c or "down" in c for c in calls)


@pytest.mark.parametrize(
    "flags", [("--reset",), ("--seed", "42"), ("--offline",), ("--profile", "demo"), ("--with-tgbot",), ("--restart",)]
)
def test_restart_cannot_be_combined_with_install_options(tmp_path: Path, flags: tuple[str, ...]):
    result, calls = run_restart(tmp_path, flags=flags)
    assert result.returncode == 2 and calls == []


def test_failed_build_keeps_reason_only_in_private_log(tmp_path: Path, monkeypatch, capsys):
    spec = importlib.util.spec_from_file_location("install_preflight_private", ROOT / "scripts/install_preflight.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 1, "builder output", "PyPI hatchling timeout; synthetic-secret"),
    )
    monkeypatch.setattr(module.tempfile, "tempdir", str(tmp_path))
    with pytest.raises(RuntimeError, match=r"Приватный лог \(0600\):") as error:
        module.docker("compose", "build", private_log=True)
    assert "synthetic-secret" not in str(error.value)
    assert "bash ./install.sh --restart" in str(error.value)
    path = Path(str(error.value).splitlines()[0].split(": ", 1)[1])
    assert path.parent == tmp_path and stat.S_IMODE(path.stat().st_mode) == 0o600
    assert "PyPI hatchling timeout; synthetic-secret" in path.read_text()
    assert capsys.readouterr().out == ""


def restart_helper():
    spec = importlib.util.spec_from_file_location("install_restart_cases", ROOT / "scripts/install_restart.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fake_clock(monkeypatch, module):
    from types import SimpleNamespace

    value = [0.0]
    monkeypatch.setattr(
        module,
        "time",
        SimpleNamespace(monotonic=lambda: value[0], sleep=lambda delay: value.__setitem__(0, value[0] + delay)),
    )
    return value


def test_postgres_never_healthy_does_not_restart_apps(monkeypatch):
    helper = restart_helper()
    clock = fake_clock(monkeypatch, helper)
    plan = {name: {"id": IDS[name], "running": True} for name in ("postgres", "backend", "personal")}
    monkeypatch.setattr(helper, "inspect_plan", lambda *_a: plan)
    calls = []

    def docker(*args, **_kwargs):
        calls.append(args)
        return "unhealthy"

    monkeypatch.setattr(helper, "docker", docker)
    with pytest.raises(helper.RestartError, match="PostgreSQL не готов"):
        helper.restart_services()
    assert clock[0] == 120
    assert calls and all(args[0] == "inspect" for args in calls)


@pytest.mark.parametrize("timed_out", [False, True])
def test_http_readiness_deadline_bounds_failures_and_timeouts(monkeypatch, timed_out):
    from types import SimpleNamespace

    helper = restart_helper()
    clock = fake_clock(monkeypatch, helper)
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        clock[0] += kwargs["timeout"] if timed_out else 1
        if timed_out:
            raise subprocess.TimeoutExpired(args, kwargs["timeout"])
        return subprocess.CompletedProcess(args, 22)

    monkeypatch.setattr(helper, "subprocess", SimpleNamespace(run=run, TimeoutExpired=subprocess.TimeoutExpired))
    with pytest.raises(helper.RestartError, match="Не подтверждена готовность"):
        helper.wait_http("http://127.0.0.1:32123/owned-only", budget=5)
    assert clock[0] == 5
    assert calls and all(0 < item[1]["timeout"] <= 5 for item in calls)
    assert all(item[0][1:3] == ["--noproxy", "*"] for item in calls)


@pytest.mark.parametrize(
    "service,body",
    [
        ("backend", b'{"status":"degraded","db":false}'),
        ("backend", b'{"status":"ok","db":false}'),
        ("backend", b'{"status":"ok","db":1}'),
        ("backend", b'{"status":"ok","db":"true"}'),
        ("backend", b'{"status":"ok"}'),
        ("personal", b'{"status":true}'),
        ("personal", b'{"status":"degraded"}'),
        ("personal", b"[]"),
        ("personal", b"not json"),
    ],
)
def test_http_200_unready_body_keeps_polling_until_deadline(monkeypatch, service, body):
    helper = restart_helper()
    clock = fake_clock(monkeypatch, helper)
    monkeypatch.setattr(helper.subprocess, "run", lambda args, **kw: subprocess.CompletedProcess(args, 0, body))
    with pytest.raises(helper.RestartError, match="Не подтверждена готовность"):
        helper.wait_http("http://127.0.0.1:32123/owned-only", budget=5, service=service)
    assert clock[0] == 5


@pytest.mark.parametrize("service,body", [("backend", b'{"status":"ok","db":true}'), ("personal", b'{"status":"ok"}')])
def test_http_readiness_requires_native_service_body(monkeypatch, service, body):
    helper = restart_helper()
    clock = fake_clock(monkeypatch, helper)
    responses = iter([b'{"status":"degraded"}', body])
    monkeypatch.setattr(
        helper.subprocess, "run", lambda args, **kw: subprocess.CompletedProcess(args, 0, next(responses))
    )
    helper.wait_http("http://127.0.0.1:32123/owned-only", budget=5, service=service)
    assert clock[0] == 2
