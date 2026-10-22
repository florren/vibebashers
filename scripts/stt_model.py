"""Скачивает малую русскую модель Vosk в data/models/stt (B10). Идемпотентно: при наличии каталога ничего не делает.

Использование: python3 scripts/stt_model.py [--model vosk-model-small-ru-0.22] [--dest data/models/stt]
"""

from __future__ import annotations

import argparse
import io
import sys
import urllib.request
import zipfile
from pathlib import Path

BASE = "https://alphacephei.com/vosk/models/"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="vosk-model-small-ru-0.22")
    ap.add_argument("--dest", default=str(Path(__file__).resolve().parents[1] / "data" / "models" / "stt"))
    a = ap.parse_args()
    dest = Path(a.dest)
    target = dest / a.model
    if (target / "conf").exists() or (target / "am").exists():
        print(f"модель уже есть: {target}")  # noqa: T201
        return 0
    dest.mkdir(parents=True, exist_ok=True)
    url = f"{BASE}{a.model}.zip"
    print(f"скачиваем {url} …")  # noqa: T201
    with urllib.request.urlopen(url, timeout=120) as r:  # noqa: S310
        total = int(r.headers.get("Content-Length") or 0)
        buf = io.BytesIO()
        got = 0
        while chunk := r.read(1 << 20):
            buf.write(chunk)
            got += len(chunk)
            if total:
                print(f"\r  {got / 1e6:.1f} / {total / 1e6:.1f} МБ", end="", file=sys.stderr)  # noqa: T201
    print()  # noqa: T201
    buf.seek(0)
    with zipfile.ZipFile(buf) as z:
        z.extractall(dest)
    print(f"готово: {target}")  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
