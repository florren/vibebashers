"""Очередь единственного PERS-потока с ограниченным приоритетом разбора HITL."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar

_HUMAN_DECISION: ContextVar[bool] = ContextVar("llm_human_decision", default=False)


@contextmanager
def human_decision_generation(enabled: bool) -> Iterator[None]:
    token = _HUMAN_DECISION.set(enabled)
    try:
        yield
    finally:
        _HUMAN_DECISION.reset(token)


class GenerationQueue:
    """Не более двух HITL подряд при наличии обычных запросов; FIFO внутри класса."""

    def __init__(self) -> None:
        self._regular: deque[asyncio.Future[None]] = deque()
        self._human: deque[asyncio.Future[None]] = deque()
        self._held = False
        self._human_streak = 0

    def _wake_next(self) -> None:
        if self._held:
            return
        for queue in (self._regular, self._human):
            while queue and queue[0].cancelled():
                queue.popleft()
        if not self._regular and not self._human:
            self._human_streak = 0
            return
        if self._human and (not self._regular or self._human_streak < 2):
            waiter = self._human.popleft()
            self._human_streak = min(2, self._human_streak + 1)
        else:
            waiter = self._regular.popleft()
            self._human_streak = 0
        self._held = True
        waiter.set_result(None)

    def _release(self) -> None:
        self._held = False
        self._wake_next()

    @asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        waiter = asyncio.get_running_loop().create_future()
        queue = self._human if _HUMAN_DECISION.get() else self._regular
        queue.append(waiter)
        self._wake_next()
        try:
            await waiter
        except asyncio.CancelledError:
            # Отмена возможна и после выдачи слота, до возобновления владельца.
            if not waiter.cancelled():
                self._release()
            elif waiter in queue:
                queue.remove(waiter)
            raise
        try:
            yield
        finally:
            self._release()
