"""JSONL-приёмник structlog: каждая запись лога — строка JSON в var/log/app.jsonl (ротация по размеру).

Файл читают и люди (`tail -f | jq`), и агенты (`scripts/quality_report.py` агрегирует warning/error по событиям).
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

import structlog

LEVELS = {"debug": 10, "info": 20, "warning": 30, "warn": 30, "error": 40, "critical": 50, "exception": 40}


class JsonlSink:
    """Процессор structlog: пишет событие в файл и возвращает его дальше по цепочке без изменений."""

    def __init__(
        self, path: Path, *, max_bytes: int = 20 * 1024 * 1024, backups: int = 3, min_level: str = "info"
    ) -> None:
        self.path = path
        self.max_bytes = max_bytes
        self.backups = backups
        self.min_level = LEVELS.get(min_level, 20)
        self._lock = threading.Lock()
        self.written = 0
        self.failed = 0

    def __call__(self, logger: Any, method: str, event_dict: structlog.types.EventDict) -> structlog.types.EventDict:
        if LEVELS.get(str(event_dict.get("level", method)), 20) < self.min_level:
            return event_dict
        line = json.dumps(event_dict, ensure_ascii=False, default=str)
        try:
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                if self.path.exists() and self.path.stat().st_size > self.max_bytes:
                    self._rotate()
                with self.path.open("a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
                self.written += 1
        except OSError:
            self.failed += 1  # журнал не должен ломать приложение
        return event_dict

    def _rotate(self) -> None:
        for i in range(self.backups - 1, 0, -1):
            src = self.path.with_suffix(f".jsonl.{i}")
            if src.exists():
                os.replace(src, self.path.with_suffix(f".jsonl.{i + 1}"))
        os.replace(self.path, self.path.with_suffix(".jsonl.1"))


def read_tail(
    path: Path, *, limit: int = 200, min_level: str = "warning", event: str | None = None
) -> list[dict[str, Any]]:
    """Последние записи JSONL (с конца файла), отфильтрованные по уровню/событию — для API и отчёта."""
    if not path.exists():
        return []
    threshold = LEVELS.get(min_level, 30)
    out: list[dict[str, Any]] = []
    with path.open("rb") as fh:
        fh.seek(0, 2)
        size = fh.tell()
        chunk = min(size, 2 * 1024 * 1024)
        fh.seek(size - chunk)
        lines = fh.read().decode("utf-8", errors="replace").splitlines()
    for raw in reversed(lines):
        try:
            rec = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if LEVELS.get(str(rec.get("level", "info")), 20) < threshold:
            continue
        if event and rec.get("event") != event:
            continue
        out.append(rec)
        if len(out) >= limit:
            break
    return out


def summarize(path: Path, *, min_level: str = "warning", limit: int = 5000) -> dict[str, Any]:
    """Сводка по JSONL: счётчик warning/error по событию с последним примером."""
    recs = read_tail(path, limit=limit, min_level=min_level)
    by_event: dict[str, dict[str, Any]] = {}
    for r in recs:
        key = f"{r.get('level')}:{r.get('event')}"
        slot = by_event.setdefault(key, {"level": r.get("level"), "event": r.get("event"), "count": 0, "last": None})
        slot["count"] += 1
        if slot["last"] is None:
            slot["last"] = {k: v for k, v in r.items() if k not in ("event", "level")}
    items = sorted(by_event.values(), key=lambda x: -x["count"])
    return {"file": str(path), "records": len(recs), "items": items[:50]}
