#!/usr/bin/env python3
"""T-269: управляемый публичный туннель; ключ читается как данные из .env, не исполняется shell."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

SUBDOMAIN = "royal-penguin-6552"
ARGS = [
    "http",
    "9999",
    f"--subdomain={SUBDOMAIN}",
    "--rate-limit=10",
    "--https-redirect",
    "--inspect=false",
]


def env_values(path: Path) -> dict[str, str]:
    result = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(
            r"^\s*(?:export\s+)?(TUNA_API_KEY|TUNA_TOKEN|TUNA_ENABLED)\s*=\s*(.*)$",
            line,
        )
        if not match:
            continue
        value = match[2].strip()
        if value.startswith(('"', "'")):
            quote = value[0]
            end = value.find(quote, 1)
            if end < 0:
                raise ValueError("Незакрытая кавычка настройки Tuna")
            value = value[1:end]
        else:
            value = value.split(" #", 1)[0].strip()
        result[match[1]] = value
    return result


def identity(pid: int) -> str | None:
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
    except (OSError, IndexError):
        return None


def managed(state: dict[str, object]) -> bool:
    try:
        pid = int(str(state["pid"]))
        cmd = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
        return (
            identity(pid) == state.get("start")
            and b"http" in cmd
            and b"9999" in cmd
            and f"--subdomain={SUBDOMAIN}".encode() in cmd
        )
    except (OSError, KeyError, ValueError):
        return False


def stop(state_path: Path) -> None:
    if not state_path.exists():
        return
    state = json.loads(state_path.read_text())
    if managed(state):
        os.kill(int(state["pid"]), signal.SIGTERM)
        for _ in range(30):
            if not managed(state):
                break
            time.sleep(0.1)
        else:
            raise RuntimeError(
                "Туннель не завершился; принудительное завершение не выполнялось"
            )
    state_path.unlink(missing_ok=True)


def forwarding_url(log_path: Path) -> str | None:
    """Адрес берётся из Forwarding CLI: зона зависит от плана Tuna, не выдумывается."""
    if not log_path.exists():
        return None
    with log_path.open("rb") as stream:
        stream.seek(0, 2)
        stream.seek(max(0, stream.tell() - 65536))
        tail = stream.read(65536).decode(errors="replace")
    for line in reversed(tail.splitlines()[-100:]):
        try:
            row = json.loads(line)
            url = row.get("url", "")
            parsed = urlsplit(url)
            host = parsed.hostname or ""
            if (
                row.get("msg") == "Forwarding"
                and parsed.scheme == "https"
                and host.startswith(SUBDOMAIN + ".")
                and host.endswith((".tuna.am", ".tuna.free"))
                and parsed.port is None
                and parsed.username is None
                and parsed.password is None
                and not parsed.query
                and not parsed.fragment
                and parsed.path in ("", "/")
            ):
                return url.rstrip("/")
        except (ValueError, AttributeError):
            continue
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("action", choices=["start", "stop"])
    ap.add_argument("--env-file", type=Path, default=Path(".env"))
    args = ap.parse_args()
    root = args.env_file.resolve().parent
    folder = root / ".cx" / "personal-tunnel"
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    folder.chmod(0o700)
    state_path = folder / "state.json"
    if args.action == "stop":
        stop(state_path)
        print("Управляемый туннель остановлен")
        return 0
    values = env_values(args.env_file)
    key = values.get("TUNA_API_KEY") or values.get("TUNA_TOKEN")
    if values.get("TUNA_ENABLED", "1").lower() in ("0", "false", "no"):
        stop(state_path)
        print("Туннель выключен TUNA_ENABLED; локальный чат: http://localhost:9999")
        return 0
    if not key:
        stop(state_path)
        print(
            "Туннель не настроен: добавьте TUNA_API_KEY в .env. Локальный чат: http://localhost:9999"
        )
        return 0
    binary = shutil.which("tuna")
    if not binary:
        raise RuntimeError(
            "tuna не установлен: https://tuna.am/docs/guides/install/install-cli/"
        )
    with urllib.request.urlopen(
        "http://127.0.0.1:9999/api/personal/health", timeout=5
    ) as response:
        if response.status != 200:
            raise RuntimeError("Пользовательский интерфейс на 9999 не готов")
    fingerprint = hashlib.sha256(key.encode()).hexdigest()
    current = json.loads(state_path.read_text()) if state_path.exists() else {}
    if not (managed(current) and current.get("key_fingerprint") == fingerprint):
        stop(state_path)
        log_path = folder / "tuna.log"
        # Не сохраняем ключ в командной строке или state; stdout недоступен внешним пользователям.
        log_fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        env = {k: v for k, v in os.environ.items() if not k.startswith("TUNA_")}
        key_name = "TUNA_API_KEY" if values.get("TUNA_API_KEY") else "TUNA_TOKEN"
        env.update(
            {
                key_name: key,
                "TUNA_TUI": "0",
                "TUNA_NO_PROMPT": "1",
                "TUNA_LOG_FORMAT": "json",
                "TUNA_LOG_LEVEL": "info",
            }
        )
        try:
            proc = subprocess.Popen(
                [binary, *ARGS],
                stdin=subprocess.DEVNULL,
                stdout=log_fd,
                stderr=subprocess.STDOUT,
                env=env,
                start_new_session=True,
            )
        finally:
            os.close(log_fd)
        current = {
            "pid": proc.pid,
            "start": identity(proc.pid),
            "key_fingerprint": fingerprint,
        }
        state_path.write_text(json.dumps(current))
        state_path.chmod(0o600)
    for _ in range(15):
        if not managed(current):
            raise RuntimeError(
                "Tuna завершился. Проверьте ключ, поддомен и приватный .cx/personal-tunnel/tuna.log"
            )
        public_url = forwarding_url(folder / "tuna.log")
        if not public_url:
            time.sleep(1)
            continue
        try:
            with urllib.request.urlopen(public_url, timeout=3) as response:
                body = response.read(65536)
                if (
                    response.status == 200
                    and b"/assets/personal-" in body
                    and b'id="root"' in body
                ):
                    print(
                        f"Публичный чат: {public_url} (проверен HTTPS, инспектор выключен)"
                    )
                    return 0
        except OSError:
            pass
        time.sleep(1)
    raise RuntimeError(
        "Туннель запущен, но публичный HTTPS-адрес не подтвердил готовность; проверьте соединение и поддомен"
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Tuna: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
