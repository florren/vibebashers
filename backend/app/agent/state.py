"""AgentState (T-056): состояние одного прохода графа; сериализуется в JSON целиком (чекпоинт в agent_steps)."""

from __future__ import annotations

from typing import Any, TypedDict

GRAPH_VERSION = "v1"


class AgentState(TypedDict, total=False):
    run_id: int  # sim_runs.id — прокидывается во все инструменты и строки БД
    agent_run_id: int
    thread_id: str  # f"{run_id}:{signal_id}"
    signal: dict[str, Any]
    client: dict[str, Any] | None
    context: dict[str, Any]
    normalization: dict[str, Any]
    classification: dict[str, Any]
    decision: dict[str, Any]
    human: dict[str, Any] | None  # решение человека (human_decisions)
    actions: list[dict[str, Any]]  # что сделал узел act (идемпотентность при повторном входе)
    errors: list[str]
    current_node: str
    outcome: str | None
    llm_source: str  # live | replay | mock
    prompt_version: str


def new_state(run_id: int, signal: dict[str, Any], agent_run_id: int, prompt_version: str) -> AgentState:
    return AgentState(
        run_id=run_id,
        agent_run_id=agent_run_id,
        thread_id=f"{run_id}:{signal['id']}",
        signal=signal,
        client=None,
        context={},
        normalization={},
        classification={},
        decision={},
        human=None,
        actions=[],
        errors=[],
        current_node="ingest",
        outcome=None,
        llm_source="mock",
        prompt_version=prompt_version,
    )
