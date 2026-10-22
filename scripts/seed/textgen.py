"""Шим: генератор текстов живёт в backend/app/sim/textgen.py (общий для сида и симулятора).

Локально backend не установлен как пакет — добавляем `backend/` в sys.path; в контейнере backend лежит в /app
(WORKDIR, см. backend/Dockerfile) — добавляем и его."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
for _candidate in (_ROOT / "backend", Path("/app")):
    if (_candidate / "app" / "sim" / "textgen.py").exists() and str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))

from app.sim.textgen import STYLE_SHARE, Generated, TextGen  # noqa: E402

__all__ = ["STYLE_SHARE", "Generated", "TextGen"]
