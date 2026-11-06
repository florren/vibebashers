"""Перезапуск существующего стенда: без сборки, загрузок и инициализации данных."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SERVICES = ("postgres", "backend", "personal")


class RestartError(RuntimeError):
    """Нельзя безопасно выполнить cached restart."""


def docker(*args: str, root: Path = ROOT, timeout: float = 15) -> str:
    try:
        result = subprocess.run(["docker", *args], cwd=root, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RestartError(f"Docker недоступен или не ответил ({type(error).__name__})") from None
    if result.returncode:
        raise RestartError(f"Docker-команда {args[0]} не выполнена; автоматическая установка или сброс не запускаются")
    return result.stdout


def inspect_plan(root: Path = ROOT) -> dict[str, dict[str, Any]]:
    for tool in ("docker", "curl"):
        if shutil.which(tool) is None:
            raise RestartError(f"Для --restart нужен {tool}")
    docker("info", root=root)
    docker("compose", "version", root=root)
    plan = {}
    projects = set()
    for service in SERVICES:
        candidates = docker("compose", "ps", "--all", "--quiet", service, root=root).split()
        regular = []
        for container in candidates:
            if re.fullmatch(r"[0-9a-f]{12,64}", container) is None:
                raise RestartError("Docker вернул некорректный ID контейнера")
            labels = json.loads(docker("inspect", "--format", "{{json .Config.Labels}}", container, root=root)) or {}
            if labels.get("com.docker.compose.oneoff", "").lower() == "true":
                continue
            if (
                labels.get("com.docker.compose.service") != service
                or labels.get("com.docker.compose.oneoff", "").lower() != "false"
            ):
                raise RestartError(f"Контейнер {service} не является штатным Compose service")
            projects.add(labels.get("com.docker.compose.project"))
            metadata = json.loads(
                docker(
                    "inspect",
                    "--format",
                    '{"image":{{json .Image}},"running":{{json .State.Running}},"healthcheck":{{json .Config.Healthcheck}}}',
                    container,
                    root=root,
                )
            )
            image = metadata["image"]
            if (
                not isinstance(image, str)
                or re.fullmatch(r"sha256:[0-9a-f]{64}", image) is None
                or type(metadata["running"]) is not bool
            ):
                raise RestartError(f"Не подтверждены образ или состояние {service}")
            if docker("image", "inspect", "--format", "{{.Id}}", image, root=root).strip() != image:
                raise RestartError(f"Локальный образ {service} не совпадает с контейнером")
            regular.append({"id": container, **metadata})
        if len(regular) != 1:
            raise RestartError(f"Нужен ровно один существующий контейнер {service}; --restart ничего не создаёт")
        plan[service] = regular[0]
    if len(projects) != 1 or None in projects or "" in projects:
        raise RestartError("Контейнеры относятся к разным или неизвестным Compose projects")
    check = plan["postgres"].get("healthcheck")
    if not check or not check.get("Test") or check["Test"][0] == "NONE":
        raise RestartError("У существующего PostgreSQL не задан healthcheck; требуется диагностика")
    return plan


def wait_postgres(container: str, root: Path = ROOT, budget: float = 120) -> None:
    deadline = time.monotonic() + budget
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        state = docker(
            "inspect",
            "--format",
            "{{if .State.Health}}{{.State.Health.Status}}{{end}}",
            container,
            root=root,
            timeout=max(0.1, min(10, remaining)),
        ).strip()
        if state == "healthy":
            return
        time.sleep(max(0, min(2, deadline - time.monotonic())))
    raise RestartError("PostgreSQL не готов за 120 с; приложения не перезапускались")


def wait_http(url: str, budget: float = 120) -> None:
    deadline = time.monotonic() + budget
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        limit = str(max(0.1, min(5, remaining)))
        try:
            result = subprocess.run(
                ["curl", "--noproxy", "*", "--connect-timeout", limit, "--max-time", limit, "-fs", url],
                capture_output=True,
                timeout=max(0.1, remaining),
            )
        except (OSError, subprocess.TimeoutExpired):
            result = None
        if result is not None and result.returncode == 0:
            return
        time.sleep(max(0, min(2, deadline - time.monotonic())))
    raise RestartError(f"Не подтверждена готовность {url}; повторной установки или сброса нет")


def restart_services(
    root: Path = ROOT,
    health_urls: tuple[str, str] = ("http://127.0.0.1:8000/api/health", "http://127.0.0.1:9999/api/personal/health"),
) -> None:
    plan = inspect_plan(root)
    postgres = plan["postgres"]
    if not postgres["running"]:
        docker("start", postgres["id"], root=root, timeout=30)
    wait_postgres(postgres["id"], root)
    docker("restart", "--time", "120", plan["backend"]["id"], plan["personal"]["id"], root=root, timeout=270)
    for url in health_urls:
        wait_http(url)


def main() -> int:
    try:
        restart_services()
    except (RestartError, ValueError, KeyError) as error:
        sys.stderr.write(f"Перезапуск остановлен: {error}\n")
        return 1
    sys.stdout.write("Существующий стенд перезапущен и готов: http://localhost:8000 · http://localhost:9999\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
