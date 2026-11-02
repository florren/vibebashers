"""T-041: durable LangGraph checkpoints в одной транзакции с эффектами узла."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import psycopg
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from psycopg.rows import DictRow


class TransactionalSaver(AsyncPostgresSaver):
    """sync durability фиксирует эффекты и следующий checkpoint вместе.

    Соединение принадлежит одному исполняемому треду. Runtime не вызывает setup:
    таблицы и upstream версии создаёт миграция 0012. Pickle и расширенные
    конструкторы запрещены: AgentState содержит только JSON-значения.
    """

    def __init__(self, conn: psycopg.AsyncConnection[Any]) -> None:
        super().__init__(
            conn,
            serde=JsonPlusSerializer(pickle_fallback=False, allowed_json_modules=[], allowed_msgpack_modules=[]),
        )
        self.owner = conn
        self.owner_lock = asyncio.Lock()

    @asynccontextmanager
    async def _cursor(self, *, pipeline: bool = False) -> AsyncIterator[psycopg.AsyncCursor[DictRow]]:
        # T-056 требует отдельную schema; настройка действует лишь внутри IO
        # saver и восстанавливается до передачи соединения доменному узлу.
        async with super()._cursor(pipeline=pipeline) as cur:
            await cur.execute("select current_setting('search_path') as value")
            row = await cur.fetchone()
            assert row is not None
            old = row["value"]
            await cur.execute("select set_config('search_path','langgraph,public',true)")
            try:
                yield cur
            finally:
                await cur.execute("select set_config('search_path',%s,true)", (old,))

    async def aput(self, config: Any, checkpoint: Any, metadata: Any, new_versions: Any) -> Any:
        async with self.owner_lock:
            result = await super().aput(config, checkpoint, metadata, new_versions)
            await self.owner.commit()
            return result

    async def aput_writes(self, config: Any, writes: Any, task_id: str, task_path: str = "") -> None:
        async with self.owner_lock:
            await super().aput_writes(config, writes, task_id, task_path)

    async def aget_tuple(self, config: Any) -> Any:
        async with self.owner_lock:
            return await super().aget_tuple(config)
