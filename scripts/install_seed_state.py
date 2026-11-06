"""Read-only проверка памяти backend после installer seed; exit3 требует reload."""

from __future__ import annotations

import json
import sys
import urllib.request
from typing import Any


class InstallStateError(ValueError):
    """Неполное или активное состояние нельзя автоматически перезапускать."""


def decision(memory: dict[str, Any], row: tuple[Any, ...] | None) -> int:
    if row is None or row[0] is None or row[2] is None or row[3] is None:
        raise InstallStateError("После seed не найден текущий запуск в БД")
    if "current_run_id" not in memory:
        raise InstallStateError("Backend не вернул current_run_id")
    current = memory["current_run_id"]
    if current is not None and (type(current) is not int or current <= 0):
        raise InstallStateError("Backend вернул некорректный current_run_id")
    if not isinstance(memory.get("running"), bool):
        raise InstallStateError("Backend не вернул состояние running")
    run_id, running, kind, status, active, pending = row
    if current == run_id:
        return 0
    if (
        current is not None
        or memory["running"]
        or running
        or kind != "baseline"
        or status != "completed"
        or active
        or pending
    ):
        raise InstallStateError(
            "Память backend отличается от БД; активный или не initial baseline требует ручной диагностики"
        )
    return 3


def check_state(dsn: str, state_url: str = "http://127.0.0.1:8000/api/sim/state") -> int:
    import psycopg

    with urllib.request.urlopen(state_url, timeout=5) as response:
        memory = json.load(response)
    if not isinstance(memory, dict):
        raise InstallStateError("Backend не вернул объект sim/state")
    with psycopg.connect(
        dsn, connect_timeout=5, options="-c default_transaction_read_only=on -c statement_timeout=5000"
    ) as conn:
        row = conn.execute(
            "select s.current_run_id,s.running,r.kind,r.status,"
            "exists(select 1 from agent_runs where outcome is null),"
            "exists(select 1 from signals where status in ('new','processing')) "
            "from sim_state s left join sim_runs r on r.id=s.current_run_id where s.id=1"
        ).fetchone()
    return decision(memory, row)


def main() -> int:
    import psycopg

    from app.db.session import psycopg_dsn

    try:
        return check_state(psycopg_dsn())
    except InstallStateError as error:
        sys.stderr.write(f"{error}\n")
    except (OSError, ValueError, psycopg.Error) as error:
        # Не выводим URL, конфигурацию и текст ошибок, содержащий параметры подключения.
        sys.stderr.write(f"Не удалось проверить состояние после seed ({type(error).__name__})\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
