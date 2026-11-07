"""Подтвердить listener внутри PID namespace контейнера с host-сетью (Linux)."""

from __future__ import annotations

import sys
from pathlib import Path


def owns_listener(port: int, proc: Path = Path("/proc")) -> bool:
    listeners = set()
    for name in ("tcp", "tcp6"):
        try:
            lines = (proc / "net" / name).read_text().splitlines()[1:]
        except FileNotFoundError:
            continue
        for line in lines:
            fields = line.split()
            if (
                len(fields) >= 10
                and fields[3] == "0A"
                and int(fields[1].rsplit(":", 1)[1], 16) == port
            ):
                listeners.add(f"socket:[{fields[9]}]")
    if not listeners:
        return False
    # /proc/net в host-сети включает чужие sockets. Только fd процессов этого
    # PID namespace доказывают владение; исчезнувший/недоступный fd не доказательство.
    for process in proc.iterdir():
        if not process.name.isdecimal():
            continue
        try:
            for fd in (process / "fd").iterdir():
                try:
                    if str(fd.readlink()) in listeners:
                        return True
                except (FileNotFoundError, PermissionError):
                    continue
        except (FileNotFoundError, PermissionError):
            continue
    return False


if __name__ == "__main__":
    if (
        len(sys.argv) != 2
        or not sys.argv[1].isascii()
        or not sys.argv[1].isdigit()
        or not 1 <= int(sys.argv[1]) <= 65535
    ):
        sys.exit(2)
    sys.exit(0 if owns_listener(int(sys.argv[1])) else 1)
