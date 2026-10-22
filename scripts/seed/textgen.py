"""Шим: генератор текстов живёт в backend/app/sim/textgen.py (общий для сида и симулятора)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from app.sim.textgen import STYLE_SHARE, Generated, TextGen  # noqa: E402

__all__ = ["STYLE_SHARE", "Generated", "TextGen"]
