"""Тексты demo-сотрудников: единая цепочка LLM и явно помеченный детерминированный резерв."""

from __future__ import annotations

from typing import Any

from app.agent.prompts import load
from app.contracts.events.demo.role_response import RoleResponse
from app.contracts.registry import deref, validate
from app.llm.base import LLMProfile, Message
from app.llm.failover import ProviderChain
from app.llm.mock import MOCK_HINT_END, MOCK_HINT_START
from app.sim.events import dumps


async def respond(
    chain: ProviderChain, profile: LLMProfile, context: dict[str, Any], fallback: str, decision: str = "accept"
) -> tuple[dict[str, Any], dict[str, Any]]:
    role = context.get("role")
    if role == "product_team":
        instructions = (
            "Напиши внутренний отчёт команды о текущем этапе stage. Единственный текущий результат — result. "
            "outcome задаёт траекторию целиком. Если verified=false, проверка устранения ещё не выполнена: "
            "не объявляй проблему решённой. Если verified=true, сообщи именно подтверждённый result, "
            "а не исходную жалобу. Для RCA — причина, для fix_decision — план, для release_note — внедрение без проверки."
        )
    elif role == "customer_reply":
        instructions = (
            "Напиши конечный ответ непосредственно клиенту от Банка, обращайся на Вы. "
            "Основа ответа — подтверждённые facts. При outcome=success сообщи результат рассмотрения и закрытие обращения. "
            "Не заменяй итог обещанием проверить позднее. При outcome=unresolved явно сообщи, что проблема не решена, "
            "обращение открыто и передано на эскалацию. Не используй внутренние названия систем и Mock-АБС."
        )
    elif role == "branch_manager":
        instructions = (
            "Руководитель подтверждает разбор нарушения по confirmed_quotes и recommendation: decision=open_incident."
        )
    else:
        instructions = (
            "Оператор оценивает proposal в пределах правил: decision=accept или reject. "
            "Объясни, почему согласовано или отклонено именно это предложение; не объявляй проблему решённой."
        )
    prompt = load("demo_role", "v2").render(instructions=instructions)
    messages: list[Message] = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": dumps(context)},
    ]
    # Эталон по фактам задаёт детерминированный ответ последнего mock-провайдера.
    hint = {"body": fallback[:2000], "decision": decision}
    messages.append({"role": "assistant", "content": MOCK_HINT_START + dumps(hint) + MOCK_HINT_END})
    result = await chain.complete_structured(messages, deref("demo/role_response"), profile)
    errors = validate(result.obj, "demo/role_response")
    if errors:
        raise ValueError("demo/role_response: " + "; ".join(errors[:2]))
    return RoleResponse.model_validate(result.obj).model_dump(mode="json"), {
        "demo": True,
        "source": result.usage.source,
        "model": result.usage.model,
        "provider": result.provider,
        "usage": result.usage.as_dict(),
        "prompt_version": "demo-role-v2",
        "fallback": result.fallback_mock,
    }


async def finish_run(conn: Any, agent_run_id: int, meta: dict[str, Any]) -> None:
    usage = meta.get("usage") or {}
    await conn.execute(
        "update agent_runs set outcome=%s,finished_at=now(),total_tokens=%s,prompt_tokens=%s,completion_tokens=%s,total_latency_ms=%s,cost_estimate=%s where id=%s",
        (
            "fallback_mock" if meta.get("fallback") else "completed",
            int(usage.get("total_tokens") or 0),
            int(usage.get("prompt_tokens") or 0),
            int(usage.get("completion_tokens") or 0),
            int(usage.get("latency_ms") or 0),
            float(usage.get("cost_rub") or 0),
            agent_run_id,
        ),
    )
