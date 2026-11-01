"""T-067: сравнение на одном снимке данных, с записью только диагностического следа.

Доменные чтения выполняются в PostgreSQL READ ONLY. agent_runs/agent_steps пишутся
отдельным соединением: отмена сравнения не меняет обращение или настоящий проход.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import math
import time
from collections import deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import psycopg
from fastapi import HTTPException, Request

from app.agent import nodes
from app.agent.graph import _load_signal, load_deps
from app.agent.nodes import Deps
from app.agent.prompts import load, prompt_version
from app.agent.state import AgentState, new_state
from app.agent.tools.base import ToolContext
from app.contracts.registry import deref, validate
from app.db.session import psycopg_dsn
from app.llm.base import LLMProfile
from app.llm.failover import ProviderChain
from app.llm.mock import MockProvider
from app.logging import get_logger

log = get_logger(__name__)
MOCK_PROFILE = LLMProfile(code="compare_mock", provider="mock", model="mock-rules-v1")


class JuryRateLimit:
    """Общий лимит жюри в одном backend-процессе, без доверия к proxy/IP-заголовкам."""

    def __init__(self) -> None:
        self.hits: deque[float] = deque()

    def check(self, now: float) -> None:
        while self.hits and self.hits[0] <= now - 60:
            self.hits.popleft()
        if len(self.hits) >= 20:
            retry = max(1, math.ceil(self.hits[0] + 60 - now))
            raise HTTPException(429, "Не больше 20 запросов жюри в минуту", headers={"Retry-After": str(retry)})
        self.hits.append(now)


def guard_jury_rate(request: Request) -> None:
    limiter = getattr(request.app.state, "jury_rate_limit", None)
    if limiter is None:
        limiter = JuryRateLimit()
        request.app.state.jury_rate_limit = limiter
    limiter.check(time.monotonic())


async def _create_run(
    writer: psycopg.AsyncConnection[Any],
    *,
    signal: dict[str, Any] | None,
    client_id: int | None,
    sim_time: dt.datetime,
    profile: LLMProfile,
) -> int:
    profile_row = await (await writer.execute("select id from llm_profiles where code=%s", (profile.code,))).fetchone()
    row = await (
        await writer.execute(
            "insert into agent_runs(kind,sim_run_id,signal_id,client_id,llm_profile_id,prompt_version,graph_version,started_sim) "
            "values('compare',%s,%s,%s,%s,%s,'compare-v1',%s) returning id",
            (
                signal["run_id"] if signal else None,
                signal["id"] if signal else None,
                client_id,
                profile_row[0] if profile_row else None,
                prompt_version(),
                sim_time,
            ),
        )
    ).fetchone()
    assert row is not None
    return int(row[0])


async def _finish(
    writer: psycopg.AsyncConnection[Any], deps: Deps, error: str | None = None, *, cancelled: bool = False
) -> None:
    await writer.execute(
        "update agent_runs set outcome=%s,finished_at=now(),error=%s,needed_human=false,"
        "prompt_tokens=%s,completion_tokens=%s,total_tokens=%s,total_latency_ms=%s,cost_estimate=%s where id=%s",
        (
            "cancelled" if cancelled else "failed" if error else "completed",
            error,
            int(deps.tokens["prompt"]),
            int(deps.tokens["completion"]),
            int(deps.tokens["prompt"]) + int(deps.tokens["completion"]),
            int(deps.tokens["latency_ms"]),
            deps.tokens["cost"],
            deps.ctx.agent_run_id,
        ),
    )


@dataclass
class MockComparison:
    state: AgentState
    deps: Deps
    writer: psycopg.AsyncConnection[Any]

    @property
    def id(self) -> int:
        return self.deps.ctx.agent_run_id

    async def run(self) -> int:
        try:
            # Никаких act/wait_human/check_rules: они изменяют доменные записи.
            # Общие постпроверки normalize/classify/decide остаются теми же, что у агента.
            for fn in (nodes.normalize, nodes.identify_client, nodes.gather_context, nodes.classify, nodes.decide):
                await self.deps.begin_step(fn.__name__)
                self.state = await fn(self.state, self.deps)
            if self.state["errors"]:
                raise ValueError("Сравнение не прошло проверки структурированного результата")
            await self.deps.record_step(
                "act",
                "skipped",
                {},
                {"dry_run": True, "planned_decision": self.state["decision"]},
                reasoning="Показан план mock. Инструменты записи, уведомления, деньги и HITL не исполнялись.",
            )
            await _finish(self.writer, self.deps)
        except asyncio.CancelledError:
            await _finish(self.writer, self.deps, "compare: cancelled", cancelled=True)
            raise
        except Exception as exc:
            # Ошибка видна в отдельном compare-run и не подменяет результат настоящего агента.
            log.warning("jury_comparison_failed", agent_run_id=self.id, error_type=type(exc).__name__)
            await self.deps.record_step("compare", "error", {}, {"error_type": type(exc).__name__})
            await _finish(self.writer, self.deps, f"compare: {type(exc).__name__}")
        return self.id


@asynccontextmanager
async def mock_comparison(signal_id: int) -> AsyncIterator[MockComparison]:
    async with await psycopg.AsyncConnection.connect(psycopg_dsn()) as reader:
        await reader.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        signal = await _load_signal(reader, signal_id)
        if signal is None:
            raise HTTPException(404, "Сигнал не найден")
        # Первый SELECT фиксирует снимок до запуска настоящего агента в вызывающем API.
        sim_time = dt.datetime.fromisoformat(signal["received_sim"])
        async with await psycopg.AsyncConnection.connect(psycopg_dsn(), autocommit=True) as writer:
            run_id = await _create_run(
                writer, signal=signal, client_id=signal.get("client_id"), sim_time=sim_time, profile=MOCK_PROFILE
            )
            try:
                deps = await load_deps(
                    reader,
                    chain=ProviderChain([MockProvider()]),
                    profile=MOCK_PROFILE,
                    run_id=int(signal["run_id"]),
                    agent_run_id=run_id,
                    sim_time=sim_time,
                    dry_run=True,
                    trace_conn=writer,
                )
            except BaseException as exc:
                # Подготовка также обязана закрыть диагностический запуск при отмене/ошибке.
                await writer.execute(
                    "update agent_runs set outcome=%s,finished_at=now(),error=%s where id=%s",
                    (
                        "cancelled" if isinstance(exc, asyncio.CancelledError) else "failed",
                        f"compare setup: {type(exc).__name__}",
                        run_id,
                    ),
                )
                raise
            yield MockComparison(new_state(int(signal["run_id"]), signal, run_id, prompt_version()), deps, writer)


async def _classification(
    text: str, channel: str, client_id: int | None, profile: LLMProfile, chain: ProviderChain
) -> tuple[dict[str, Any], int]:
    async with await psycopg.AsyncConnection.connect(psycopg_dsn(), autocommit=True) as writer:
        now = dt.datetime.now(dt.UTC)
        run_id = await _create_run(writer, signal=None, client_id=client_id, sim_time=now, profile=profile)
        ctx = ToolContext(writer, run_id=0, agent_run_id=run_id, sim_time=now, dry_run=True)
        deps = Deps(ctx, chain, profile)
        try:
            prompt = (
                load("system").body
                + "\n\n"
                + load("classify").render(
                    teams="", fewshot="нет", context="{}", normalization="{}", channel=channel, text=text
                )
            )
            result = await chain.complete_structured(
                [{"role": "system", "content": prompt}, {"role": "user", "content": text}],
                deref("agent/classification"),
                profile,
                context="default",
            )
            obj = nodes.prune(result.obj, deref("agent/classification"))
            if validate(obj, "agent/classification"):
                raise ValueError("Некорректная классификация сравнения")
            await deps.record_step(
                "classify",
                "fallback" if result.fallback_mock else "ok",
                {"channel": channel},
                obj,
                prompt=prompt,
                raw=result.raw,
                model=result.usage.model,
                usage=result.usage.as_dict(),
                latency_ms=result.usage.latency_ms,
            )
            await _finish(writer, deps)
            return obj, run_id
        except asyncio.CancelledError:
            await _finish(writer, deps, "compare: cancelled", cancelled=True)
            raise
        except Exception as exc:
            await deps.record_step("classify", "error", {}, {"error_type": type(exc).__name__})
            await _finish(writer, deps, f"compare: {type(exc).__name__}")
            raise


async def compare_classifications(
    text: str, channel: str, client_id: int | None, profile: LLMProfile, chain: ProviderChain
) -> tuple[tuple[dict[str, Any], int], tuple[dict[str, Any], int]]:
    results = await asyncio.gather(
        _classification(text, channel, client_id, profile, chain),
        _classification(text, channel, client_id, MOCK_PROFILE, ProviderChain([MockProvider()])),
        return_exceptions=True,
    )
    # Оба диагностических запуска должны завершить аудит до ответа с ошибкой.
    for result in results:
        if isinstance(result, BaseException):
            raise result
    main, mock = results
    assert not isinstance(main, BaseException) and not isinstance(mock, BaseException)
    return main, mock
