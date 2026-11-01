"""T-145: смоук собранного образа в отдельном Compose-проекте с mock LLM."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import subprocess
import tempfile
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def isolate(config: dict[str, Any], project: str, image: str, port: int, directory: Path) -> dict[str, Any]:
    if not project.startswith("cx-ci-") or image != "cx-pulse-backend:ci" or not 1024 <= port <= 65535:
        raise ValueError("CI требует свой project, image :ci и непривилегированный port")
    config["name"] = project
    for section in ("volumes", "networks"):
        for row in config.get(section, {}).values():
            if row.get("external") or row.get("driver_opts"):
                raise ValueError("CI не использует внешние volumes/networks")
            row.pop("name", None)
    for name, service in config["services"].items():
        if service.get("privileged") or service.get("network_mode") or service.get("volumes_from"):
            raise ValueError("неизолированная конфигурация сервиса")
        for index, mount in enumerate(service.get("volumes", [])):
            if mount["type"] != "bind":
                continue
            source = Path(mount["source"]).resolve()
            if not source.is_relative_to(ROOT.resolve()):
                raise ValueError("bind source вне отдельного checkout")
            destination = directory / "binds" / name / str(index)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if source.is_dir():
                shutil.copytree(source, destination, symlinks=False)
            elif source.is_file():
                shutil.copy2(source, destination)
            else:
                raise ValueError("bind source не существует")
            mount["source"] = str(destination)
        # Docker создаёт родителей вложенных mounts от root; готовим их в своей копии заранее.
        binds = [mount for mount in service.get("volumes", []) if mount["type"] == "bind"]
        for outer in binds:
            for inner in binds:
                relative = (
                    Path(inner["target"]).relative_to(outer["target"])
                    if Path(inner["target"]).is_relative_to(outer["target"])
                    else None
                )
                if relative is not None and relative.parts:
                    (Path(outer["source"]) / relative).parent.mkdir(parents=True, exist_ok=True)
        service.pop("container_name", None)
        service["ports"] = []
    config["services"]["postgres"]["environment"] = {
        "POSTGRES_USER": "cx",
        "POSTGRES_PASSWORD": "cx",
        "POSTGRES_DB": "cx_pulse",
    }
    shared_secret = config["services"]["backend"].get("environment", {}).get("APP_SECRET", secrets.token_hex(32))
    for name in ("backend", "personal"):
        service = config["services"][name]
        service["image"] = image
        service.pop("build", None)
        service["user"] = f"{os.getuid()}:{os.getgid()}"
        service.setdefault("environment", {}).update(
            {
                # APP_ENV=test выключает симулятор/workers; здесь проверяется настоящее изолированное приложение.
                "APP_ENV": "dev",
                "DATABASE_URL": "postgresql+psycopg://cx:cx@postgres:5432/cx_pulse",
                "APP_SECRET": shared_secret,
                "LLM_PROVIDER": "mock",
                "LLM_CHAIN": "mock",
                "LLM_RECORD": "false",
                "STT_PROVIDER": "none",
                "TELEGRAM_BOT_TOKEN": "",
                "MAILPIT_ENABLED": "false",
                "LOG_DIR": "/tmp/cx-logs",
            }
        )
    config["services"]["backend"]["ports"] = [
        {
            "target": 8000,
            "published": str(port),
            "host_ip": "127.0.0.1",
            "protocol": "tcp",
        }
    ]
    return config


def wait_health(base: str, timeout: float = 120) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(base + "/api/health", timeout=3) as response:
                if json.load(response).get("status") == "ok":
                    return
        except (OSError, ValueError):
            pass  # Старт/рестарт контейнера ещё не завершён; общий deadline обязателен.
        time.sleep(1)
    raise TimeoutError("тестовый backend не стал healthy")


def performance(base: str, seed_seconds: float) -> dict[str, Any]:
    request = urllib.request.Request(
        base + "/api/sim/control",
        data=b'{"action":"start"}',
        headers={"Content-Type": "application/json"},
    )
    report: dict[str, Any] = {
        "seed_seconds": seed_seconds,
        "samples": {},
        "violations": [],
        "method": "21 sequential requests per endpoint; nearest-rank p95; active simulator; 5000 clients",
    }
    if seed_seconds > 90:
        report["violations"].append("demo seed > 90 seconds")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            response.read()
        with urllib.request.urlopen(base + "/api/sim/state", timeout=10) as response:
            report["simulator_state"] = json.load(response)
        if not report["simulator_state"].get("running"):
            report["violations"].append("simulator is not running")
    except (OSError, ValueError) as exc:
        report["violations"].append(f"simulator start: {type(exc).__name__}")
        return report
    for path in (
        "/api/health",
        "/api/sim/state",
        "/api/signals?limit=50",
        "/api/map/heat",
        "/api/metrics/dashboard",
    ):
        timings = []
        for _ in range(21):
            started = time.perf_counter()
            try:
                with urllib.request.urlopen(base + path, timeout=15) as response:
                    response.read()
            except OSError as exc:
                report["violations"].append(f"API {path}: {type(exc).__name__}")
                break
            timings.append((time.perf_counter() - started) * 1000)
        if len(timings) != 21:
            report["samples"][path] = {"completed_requests": len(timings)}
            continue
        p95 = sorted(timings)[19]
        report["samples"][path] = {"p95_ms": p95, "max_ms": max(timings), "timings_ms": timings}
        if p95 > 300:
            report["violations"].append(f"API {path}: p95 {p95:.1f} ms > 300 ms")
    return report


@contextmanager
def own_env(path: Path):
    """O_EXCL отклоняет файлы и dangling symlinks; подменённый inode никогда не удаляется."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    identity = os.fstat(descriptor)
    try:
        with os.fdopen(descriptor, "w") as stream:
            stream.write(
                f"APP_SECRET={secrets.token_hex(32)}\nAPP_ENV=dev\nLLM_PROVIDER=mock\nLLM_CHAIN=mock\nLLM_RECORD=false\nSTT_PROVIDER=none\nMAILPIT_ENABLED=false\nTELEGRAM_BOT_TOKEN=\n"
            )
        yield
    finally:
        try:
            current = path.lstat()
        except FileNotFoundError:
            pass
        else:
            if (current.st_dev, current.st_ino) == (identity.st_dev, identity.st_ino):
                path.unlink()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="cx-pulse-backend:ci", choices=["cx-pulse-backend:ci"])
    parser.add_argument("--port", type=int, default=18080)
    parser.add_argument("--performance", action="store_true")
    args = parser.parse_args(argv)
    project = f"cx-ci-{secrets.token_hex(6)}"
    environment = {**os.environ, "E2E_BASE_URL": f"http://127.0.0.1:{args.port}"}
    with (
        own_env(ROOT / ".env"),
        tempfile.TemporaryDirectory(prefix="cx-ci-compose-") as directory,
    ):
        compiled = subprocess.run(
            [
                "docker",
                "compose",
                "-p",
                project,
                "-f",
                "docker-compose.yml",
                "config",
                "--format",
                "json",
            ],
            cwd=ROOT,
            env={**os.environ, "APP_SECRET": secrets.token_hex(32)},
            capture_output=True,
            text=True,
            check=True,
        )
        config = isolate(json.loads(compiled.stdout), project, args.image, args.port, Path(directory))
        config_path = Path(directory) / "compose.json"
        config_path.write_text(json.dumps(config))
        command = ["docker", "compose", "-p", project, "-f", str(config_path)]
        try:
            subprocess.run(
                [
                    *command,
                    "up",
                    "-d",
                    "--wait",
                    "--wait-timeout",
                    "180",
                    "postgres",
                    "backend",
                    "personal",
                ],
                check=True,
            )
            seed_started = time.perf_counter()
            subprocess.run(
                [
                    *command,
                    "exec",
                    "-T",
                    "backend",
                    "python",
                    "/scripts/seed/run.py",
                    "--if-needed",
                    "--profile",
                    "demo" if args.performance else "lite",
                    "--clients",
                    "5000" if args.performance else "200",
                ],
                check=True,
            )
            seed_seconds = time.perf_counter() - seed_started
            subprocess.run([*command, "restart", "backend", "personal"], check=True)
            wait_health(environment["E2E_BASE_URL"])
            if args.performance:
                report = performance(environment["E2E_BASE_URL"], seed_seconds)
                destination = ROOT / "frontend/performance-results"
                destination.mkdir(parents=True, exist_ok=True)
                (destination / "performance.json").write_text(json.dumps(report, indent=2))
                if report["violations"]:
                    raise ValueError("; ".join(report["violations"]))
            subprocess.run(
                ["npm", "exec", "--", "playwright", "test"],
                cwd=ROOT / "frontend",
                env=environment,
                check=True,
            )
        finally:
            subprocess.run([*command, "logs", "--no-color", "--tail", "100"], check=False)
            subprocess.run([*command, "down", "-v", "--remove-orphans"], check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
