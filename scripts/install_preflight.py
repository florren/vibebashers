"""Проверка готовности reset до удаления контейнеров и данных."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Any


def docker(*args: str) -> str:
    result = subprocess.run(["docker", *args], capture_output=True, text=True, check=False)
    if result.returncode:
        # Compose config может содержать секреты: его вывод не попадает в сообщение ошибки.
        raise RuntimeError(
            f"Docker preflight завершился с ошибкой: docker {' '.join(args)}; повторите эту команду отдельно для диагностики"
        )
    return result.stdout


def preflight(profiles: list[str]) -> None:
    compose = ["compose", *(arg for profile in profiles for arg in ("--profile", profile))]
    config: dict[str, Any] = json.loads(docker(*compose, "config", "--format", "json"))
    project = config["name"]
    # Compose уже применил .env, shell overrides, CLI profiles и '*'.
    services = config["services"]
    # down -v затрагивает все объявленные тома, включая неактивные profiles.
    for key in sorted(config.get("volumes", {})):
        volume = config["volumes"][key]
        if volume.get("external"):
            continue
        name = volume["name"]
        holders = docker("ps", "--all", "--quiet", "--filter", f"volume={name}").split()
        for holder in holders:
            labels = json.loads(docker("inspect", "--format", "{{json .Config.Labels}}", holder)) or {}
            if not (
                labels.get("com.docker.compose.project") == project
                and labels.get("com.docker.compose.service") in services
                and labels.get("com.docker.compose.oneoff", "").lower() == "false"
            ):
                raise RuntimeError(
                    f"Reset остановлен: том {name} удерживает посторонний или one-off контейнер "
                    f"{holder[:12]}. Проверьте его вручную; контейнеры автоматически не удаляются."
                )
    docker(*compose, "build")
    for image in sorted({service["image"] for service in services.values()}):
        cached = subprocess.run(["docker", "image", "inspect", image], capture_output=True, check=False)
        if cached.returncode:
            docker("pull", image)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", action="append", default=[])
    args = parser.parse_args()
    try:
        preflight(args.profile)
    except (RuntimeError, ValueError, KeyError) as error:
        sys.stderr.write(f"{error}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
