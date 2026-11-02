"""Долговечный fail-closed marker вне pg_dump, общий для двух origins."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any

from app.config import get_settings

PHASES = frozenset({"idle", "draining", "restoring", "reloading", "failed"})


class ControlError(ValueError):
    pass


class MaintenanceControl:
    def __init__(self, directory: Path | None = None) -> None:
        self._directory = directory

    @property
    def directory(self) -> Path:
        configured = get_settings().maintenance_control_dir
        return self._directory or (
            Path(configured) if configured else Path(__file__).resolve().parents[3] / "data/maintenance"
        )

    @property
    def path(self) -> Path:
        return self.directory / "control.json"

    def read(self) -> dict[str, Any] | None:
        try:
            with self.path.open("rb") as stream:
                raw = stream.read(4097)
        except FileNotFoundError:
            return None
        except OSError:
            raise ControlError("Maintenance marker недоступен; восстановление требует явной диагностики") from None
        try:
            value = json.loads(raw)
        except (ValueError, UnicodeError):
            raise ControlError("Maintenance marker повреждён; автоматическое открытие запрещено") from None
        if (
            len(raw) > 4096
            or not isinstance(value, dict)
            or set(value) != {"version", "phase", "job_id"}
            or type(value["version"]) is not int
            or value["version"] != 1
            or not isinstance(value["phase"], str)
            or value["phase"] not in PHASES
            or (value["job_id"] is not None and not isinstance(value["job_id"], str))
            or (value["phase"] == "idle" and value["job_id"] is not None)
        ):
            raise ControlError("Maintenance marker несовместим; автоматическое открытие запрещено")
        return value

    def write(self, phase: str, job_id: str | None = None) -> None:
        if phase not in PHASES or (phase == "idle" and job_id is not None):
            raise ControlError("Неверный переход maintenance marker")
        value = {"version": 1, "phase": phase, "job_id": job_id}
        temporary = self.directory / f".control-{uuid.uuid4().hex}.tmp"
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            with temporary.open("xb") as stream:
                stream.write(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(self.path)
            directory_fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            raise ControlError("Не удалось надёжно сохранить maintenance marker; admission закрыт") from None
        finally:
            temporary.unlink(missing_ok=True)

    def initialize_missing(self) -> None:
        # Caller обязан владеть exclusive PG lease. Existing failed/corrupt не очищается.
        if self.read() is None:
            self.write("idle")

    def require_idle(self) -> None:
        value = self.read()
        if value is None or value["phase"] != "idle":
            raise ControlError("Baseline maintenance не завершён; нужен явный restore recovery")
