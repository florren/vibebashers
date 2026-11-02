"""Архив/удаление завершённых запусков: FK-замыкание, изоляция и атомарный экспорт."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql
from psycopg.pq import TransactionStatus
from psycopg.rows import dict_row, tuple_row

from app.sim import baseline, run_summary, runs
from app.sim.events import dumps
from app.tgbot.storage import lock_id


class RunConflict(ValueError):
    """Операция нарушила бы область запуска или активную работу."""


Table = tuple[str, str]
RUN_TABLE: Table = ("public", "sim_runs")


@dataclass(frozen=True)
class ForeignKey:
    child: Table
    parent: Table
    child_columns: tuple[str, ...]
    parent_columns: tuple[str, ...]
    cascade: bool


async def _foreign_keys(conn: psycopg.AsyncConnection[Any]) -> list[ForeignKey]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "select array[cn.nspname,ch.relname] child,array[pn.nspname,pa.relname] parent,"
            "array(select ca.attname from unnest(c.conkey) with ordinality k(attnum,pos) "
            "join pg_attribute ca on ca.attrelid=c.conrelid and ca.attnum=k.attnum order by k.pos) child_columns,"
            "array(select ap.attname from unnest(c.confkey) with ordinality k(attnum,pos) "
            "join pg_attribute ap on ap.attrelid=c.confrelid and ap.attnum=k.attnum order by k.pos) parent_columns,"
            "c.confdeltype='c' cascade "
            "from pg_constraint c join pg_class ch on ch.oid=c.conrelid join pg_class pa on pa.oid=c.confrelid "
            "join pg_namespace cn on cn.oid=ch.relnamespace join pg_namespace pn on pn.oid=pa.relnamespace "
            "where c.contype='f' and cn.nspname in ('public','langgraph') "
            "and pn.nspname in ('public','langgraph') order by cn.nspname,ch.relname,c.conname"
        )
        rows = await cur.fetchall()
    if any(not row["child_columns"] or len(row["child_columns"]) != len(row["parent_columns"]) for row in rows):
        raise RunConflict("Некорректные пары столбцов внешнего ключа")
    if any(row["parent"] == list(RUN_TABLE) and row["parent_columns"] != ["id"] for row in rows):
        raise RunConflict("Корневой FK запуска должен ссылаться на единственный sim_runs.id")
    return [
        ForeignKey(
            child=(row["child"][0], row["child"][1]),
            parent=(row["parent"][0], row["parent"][1]),
            child_columns=tuple(row["child_columns"]),
            parent_columns=tuple(row["parent_columns"]),
            cascade=row["cascade"],
        )
        for row in rows
    ]


def _ownership(keys: list[ForeignKey]) -> dict[Table, tuple[ForeignKey, ...]]:
    # Источник принадлежности — именно FK к sim_runs, а не совпадение имени run_id:
    # agent_steps.run_id относится к agent_runs, bench_results.run_id — к bench_runs.
    paths: dict[Table, tuple[ForeignKey, ...]] = {k.child: (k,) for k in keys if k.parent == RUN_TABLE and k.cascade}
    while True:
        additions = {
            k.child: (k, *paths[k.parent]) for k in keys if k.cascade and k.parent in paths and k.child not in paths
        }
        if not additions:
            return paths
        paths.update(additions)


def _join(child: str, parent: str, edge: ForeignKey) -> sql.Composable:
    # Каждая упорядоченная пара обязательна: одного run_id недостаточно для
    # (run_id,client_id), иначе scalar owner неоднозначен или FK guard ошибочен.
    return sql.SQL(" and ").join(
        sql.SQL("{}={}").format(sql.Identifier(child, left), sql.Identifier(parent, right))
        for left, right in zip(edge.child_columns, edge.parent_columns, strict=True)
    )


def _owner(alias: str, path: tuple[ForeignKey, ...]) -> sql.Composable:
    edge = path[0]
    if edge.parent == RUN_TABLE:
        return sql.Identifier(alias, edge.child_columns[0])
    parent_alias = alias + "_p"
    return sql.SQL("(select {} from {} {} where {})").format(
        _owner(parent_alias, path[1:]),
        sql.Identifier(*edge.parent),
        sql.Identifier(parent_alias),
        _join(alias, parent_alias, edge),
    )


async def _lock_and_guard(conn: psycopg.AsyncConnection[Any], run_id: int) -> tuple[dict[str, Any], list[Table]]:
    async with conn.cursor(row_factory=tuple_row) as guard:
        await guard.execute("select pg_try_advisory_xact_lock(%s)", (lock_id("run", 0, run_id),))
        acquired = await guard.fetchone()
    if not acquired or not acquired[0]:
        raise RunConflict("Дождитесь завершения Telegram доставки запуска")
    keys = await _foreign_keys(conn)
    paths = _ownership(keys)
    # Блокируем записи на короткое время до проверки FK и purge. Иначе новая
    # межзапусковая ссылка могла бы попасть под CASCADE после успешной проверки.
    tables = set(paths) | {k.child for k in keys if k.parent in paths} | {RUN_TABLE, ("public", "sim_state")}
    await conn.execute("set local lock_timeout='5s'")
    await conn.execute(
        sql.SQL("lock table {} in share row exclusive mode").format(
            sql.SQL(",").join(sql.Identifier(*table) for table in sorted(tables))
        )
    )
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("select * from sim_runs where id=%s for update", (run_id,))
        run = await cur.fetchone()
        if run is None:
            raise LookupError("запуск не найден")
        await cur.execute("select current_run_id from sim_state where id=1")
        state = await cur.fetchone()
        if run["kind"] == "baseline" or (state and state["current_run_id"] == run_id):
            raise RunConflict("Нельзя архивировать или удалить baseline и текущий запуск")
        if run["status"] not in ("stopped", "completed", "archived"):
            raise RunConflict("Сначала завершите запуск")
        await cur.execute(
            "select 1 from agent_runs where sim_run_id=%s and outcome is null and finished_at is null limit 1",
            (run_id,),
        )
        if await cur.fetchone():
            raise RunConflict("В запуске ещё выполняется агент")
        for key in keys:
            if key.parent not in paths:
                continue
            child_owner = _owner("c", paths[key.child]) if key.child in paths else sql.SQL("null")
            await cur.execute(
                sql.SQL("select 1 from {} c join {} p on {} where {}=%s and {} is distinct from %s limit 1").format(
                    sql.Identifier(*key.child),
                    sql.Identifier(*key.parent),
                    _join("c", "p", key),
                    _owner("p", paths[key.parent]),
                    child_owner,
                ),
                (run_id, run_id),
            )
            if await cur.fetchone():
                child = key.child[1] if key.child[0] == "public" else ".".join(key.child)
                parent = key.parent[1] if key.parent[0] == "public" else ".".join(key.parent)
                raise RunConflict(f"Данные запуска используются вне его области: {child} → {parent}")
    roots = sorted(table for table, path in paths.items() if len(path) == 1)
    return dict(run), roots


async def _purge(conn: psycopg.AsyncConnection[Any], run_id: int, roots: list[Table]) -> None:
    paths = _ownership(await _foreign_keys(conn))
    if not set(roots) <= set(paths):
        raise RunConflict("FK ownership изменился после guard")
    # Явно удаляем и transitive descendants. Одного root CASCADE недостаточно:
    # immediate NO ACTION (например causes→operations) может провериться раньше
    # cascade runtime→causes. Все целевые строки удаляются в одном statement;
    # owner выражение использует каждую упорядоченную пару composite FK.
    parts = [
        sql.SQL("{} as (delete from {} t where {}=%s)").format(
            sql.Identifier(f"purge_{index}"), sql.Identifier(*table), _owner("t", paths[table])
        )
        for index, table in enumerate(sorted(paths))
    ]
    await conn.execute(sql.SQL("with {} select 1").format(sql.SQL(",").join(parts)), (run_id,) * len(parts))


def _write_archive(path: Path, content: str) -> bool:
    """Не перезаписываем чужой файл; оставшийся после crash точный экспорт пригоден для retry."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise RunConflict("Путь архива не может быть символической ссылкой")
    if path.exists():
        if path.read_text(encoding="utf-8") != content:
            raise RunConflict("Существующий архив отличается; сохраните его перед повтором")
        return False
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
            temporary = stream.name
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return True
    finally:
        if temporary:
            Path(temporary).unlink(missing_ok=True)


def read_archive(run: dict[str, Any]) -> dict[str, Any]:
    path = baseline.runs_export_dir() / f"{int(run['id'])}.json"
    if path.is_symlink() or not path.is_file():
        raise RunConflict("Файл завершённого архива недоступен")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RunConflict("Не удалось прочитать JSON архива") from exc
    if (
        not isinstance(value, dict)
        or value.get("export_version") != 1
        or not isinstance(value.get("run"), dict)
        or value["run"].get("id") != run["id"]
        or value.get("summary") != run_summary.json_values(run["summary"])
    ):
        raise RunConflict("Архив не соответствует сохранённому заголовку и summary")
    return value


async def archive(conn: psycopg.AsyncConnection[Any], run_id: int) -> dict[str, Any]:
    if conn.info.transaction_status != TransactionStatus.IDLE:
        raise RunConflict("Архивирование требует отдельного соединения вне открытой транзакции")
    created_file = False
    path = baseline.runs_export_dir() / f"{run_id}.json"
    try:
        async with conn.transaction():
            run, roots = await _lock_and_guard(conn, run_id)
            if run["status"] == "archived":
                read_archive(run)
            else:
                exported = await run_summary.export_json(conn, run_id)
                created_file = _write_archive(path, dumps(run_summary.json_values(exported)) + "\n")
                await _purge(conn, run_id, roots)
                await conn.execute(
                    "update sim_runs set status='archived',summary=%s::jsonb,export_path=%s where id=%s",
                    (dumps(run_summary.json_values(exported["summary"])), str(path), run_id),
                )
                await conn.execute("select pg_notify('runs',%s)", (dumps({"type": "archived", "run_id": run_id}),))
    except BaseException:
        if created_file:
            path.unlink(missing_ok=True)
        raise
    result = await runs.get_run(conn, run_id)
    assert result is not None
    return result


async def delete(conn: psycopg.AsyncConnection[Any], run_id: int) -> None:
    async with conn.transaction():
        _, roots = await _lock_and_guard(conn, run_id)
        await _purge(conn, run_id, roots)
        # Потомки сохраняют историю и summary, но FK на удалённый заголовок невозможен.
        await conn.execute("update sim_runs set parent_run_id=null where parent_run_id=%s", (run_id,))
        await conn.execute("delete from sim_runs where id=%s", (run_id,))
        await conn.execute("select pg_notify('runs',%s)", (dumps({"type": "deleted", "run_id": run_id}),))
    # Архив оставляем: удаление заголовка не должно уничтожать уже выгруженный артефакт.


async def prepare_for_restore(conn: psycopg.AsyncConnection[Any], rows: list[tuple[Any, ...]]) -> list[tuple[Any, ...]]:
    """Экспорт до pg_restore; archived применяется к заголовкам только после успеха restore."""
    columns = baseline.RUN_COLS.split(", ")
    kind_at = columns.index("kind")
    status_at = columns.index("status")
    result: list[tuple[Any, ...]] = []
    created: list[Path] = []
    try:
        for row in rows:
            if row[kind_at] == "baseline" or row[status_at] == "archived":
                result.append(row)
                continue
            rid = int(row[0])
            if row[status_at] in ("running", "paused", "interrupted"):
                await runs.set_run_status(conn, rid, "stopped")
            exported = await run_summary.export_json(conn, rid)
            path = baseline.runs_export_dir() / f"{rid}.json"
            if _write_archive(path, dumps(run_summary.json_values(exported)) + "\n"):
                created.append(path)
            await conn.execute(
                "update sim_runs set summary=%s::jsonb,export_path=%s where id=%s",
                (dumps(run_summary.json_values(exported["summary"])), str(path), rid),
            )
            updated = await (
                await conn.execute(f"select {baseline.RUN_COLS} from sim_runs where id=%s", (rid,))
            ).fetchone()  # noqa: S608 — имена колонок константны
            assert updated is not None
            values = list(updated)
            values[status_at] = "archived"
            result.append(tuple(values))
    except BaseException:
        for path in created:
            path.unlink(missing_ok=True)
        raise
    return result
