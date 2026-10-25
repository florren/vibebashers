"""LLM-детектор (T-185): подтверждение предварительных находок правил и отчёт по транскрипту.

Каждый вызов записывается в agent_runs(kind='compliance_detector') + agent_steps. На mock-провайдере вердикт = находки правил
(в промпт вкладывается блок <<mock_verdict>>, который MockProvider возвращает как ответ).
"""

from __future__ import annotations

import datetime as dt
import json
import time
from typing import Any

import psycopg

from app.agent.prompts import load as load_prompt
from app.compliance.rules_detector import Finding
from app.contracts.registry import deref, validate_schema
from app.llm.base import LLMProfile, Message
from app.llm.failover import ProviderChain
from app.llm.mock import MOCK_HINT_END, MOCK_HINT_START
from app.logging import get_logger
from app.sim.events import dumps

log = get_logger(__name__)


def _hint(obj: dict[str, Any]) -> str:
    return f"\n{MOCK_HINT_START}{json.dumps(obj, ensure_ascii=False)}{MOCK_HINT_END}"


def _facts_block(products: dict[str, dict[str, Any]]) -> str:
    return json.dumps(
        {k: {"name": v.get("name_ru"), **(v.get("tariffs") or {})} for k, v in products.items()}, ensure_ascii=False
    )


class Detector:
    def __init__(
        self,
        conn: psycopg.AsyncConnection[Any],
        *,
        run_id: int,
        sim_time: dt.datetime,
        chain: ProviderChain,
        profile: LLMProfile,
        session_id: int | None = None,
    ) -> None:
        self.conn, self.run_id, self.sim_time, self.chain, self.profile = conn, run_id, sim_time, chain, profile
        self.session_id = session_id
        self.tokens = 0

    async def _run(
        self,
        node: str,
        prompt_name: str,
        prompt_vars: dict[str, Any],
        schema_name: str,
        hint: dict[str, Any],
        *,
        context: str = "detector",
    ) -> tuple[dict[str, Any], int, int]:
        """Вызов модели со структурированным ответом; возвращает (obj, agent_run_id, latency_ms)."""
        prompt = load_prompt(prompt_name)
        system = load_prompt("system")
        messages: list[Message] = [
            {"role": "system", "content": system.body},
            {"role": "user", "content": prompt.render(**prompt_vars) + _hint(hint)},
        ]
        row = await (
            await self.conn.execute(
                "insert into agent_runs (kind, sim_run_id, prompt_version, graph_version, thread_id, started_sim) "
                "values ('compliance_detector', %s, %s, 'compliance-v1', %s, %s) returning id",
                (self.run_id, prompt.version, f"compliance:{self.session_id or 0}:{node}", self.sim_time),
            )
        ).fetchone()
        agent_run_id = int(row[0])  # type: ignore[index]
        t0 = time.perf_counter()
        obj: dict[str, Any] = hint
        status, outcome, err, provider, usage = (
            "ok",
            "completed",
            None,
            None,
            {"prompt_tokens": 0, "completion_tokens": 0},
        )
        try:
            res = await self.chain.complete_structured(messages, deref(schema_name), self.profile, context=context)
            got = dict(res.obj or {})
            errors = validate_schema(got, deref(schema_name))
            provider, usage = (
                res.provider,
                {"prompt_tokens": res.usage.prompt_tokens, "completion_tokens": res.usage.completion_tokens},
            )
            if errors:
                status, err = "fallback", f"ответ не по схеме: {errors[:2]}"
                log.warning("compliance_llm_invalid", node=node, errors=errors[:3])
            else:
                obj = got
        except Exception as e:  # noqa: BLE001 — сбой модели не должен ронять сессию: откат на правила
            status, outcome, err = "fallback", "fallback_mock", f"{type(e).__name__}: {str(e)[:200]}"
            log.warning("compliance_llm_error", node=node, error=err)
        ms = int((time.perf_counter() - t0) * 1000)
        self.tokens += usage["prompt_tokens"] + usage["completion_tokens"]
        await self.conn.execute(
            "insert into agent_steps (run_id, seq, node, status, input, output, prompt, reasoning, model, prompt_tokens, completion_tokens, latency_ms, started_at, finished_at) "
            "values (%s, 1, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, %s, %s, %s, now() - make_interval(secs => %s / 1000.0), now())",
            (
                agent_run_id,
                node,
                status,
                dumps({"prompt": prompt_name, "vars": {k: str(v)[:600] for k, v in prompt_vars.items()}}),
                dumps(obj),
                messages[1]["content"][:6000],
                err or ("вердикт детектора" if provider != "mock" else "mock = правила"),
                f"{provider}/{self.profile.model}" if provider else None,
                usage["prompt_tokens"],
                usage["completion_tokens"],
                ms,
                ms,
            ),
        )
        await self.conn.execute(
            "update agent_runs set finished_at = now(), outcome = %s, total_tokens = %s, prompt_tokens = %s, completion_tokens = %s, total_latency_ms = %s, error = %s where id = %s",
            (outcome, self.tokens, usage["prompt_tokens"], usage["completion_tokens"], ms, err, agent_run_id),
        )
        return obj, agent_run_id, ms

    async def verdict(
        self, finding: Finding, *, text: str, context: str, products: dict[str, dict[str, Any]]
    ) -> tuple[dict[str, Any], int, int]:
        hint = {
            "is_misselling": True,
            "pattern_code": finding.pattern_code,
            "confidence": round(float(finding.confidence), 3),
            "quote": finding.quote[:240],
            "explanation_ru": (
                "Совпадение по правилам: " + "; ".join(f"«{e}»" for e in finding.evidence[:3])
                if finding.evidence
                else "совпадение с паттерном"
            )[:300],
            "counter_argument_ru": None,
            "family": finding.family,
            "recommendation_ru": finding.recommendation_ru,
            "fact_check": ({"facts": finding.facts} if finding.facts else None),
        }
        return await self._run(
            "misselling_detect",
            "misselling_detect",
            {
                "context": context,
                "facts": _facts_block(products),
                "preliminary": json.dumps(finding.as_dict(), ensure_ascii=False),
                "text": text,
            },
            "compliance/misselling_verdict",
            hint,
        )

    async def report(
        self,
        *,
        transcript_text: str,
        findings: list[dict[str, Any]],
        script_code: str,
        script_steps: list[dict[str, Any]],
        products: dict[str, dict[str, Any]],
        overall_hint: str,
        action_hint: str,
    ) -> tuple[dict[str, Any], int, int]:
        hint = {
            "findings": findings,
            "script_compliance": {"script_code": script_code, "steps": script_steps},
            "overall_ru": overall_hint,
            "action_plan_ru": action_hint,
            "confidence": round(max([f["confidence"] for f in findings] + [0.7]), 3),
        }
        return await self._run(
            "transcript_report",
            "transcript_report",
            {
                "script_code": script_code,
                "facts": _facts_block(products),
                "preliminary": json.dumps(findings, ensure_ascii=False)[:4000],
                "script_steps": json.dumps(script_steps, ensure_ascii=False),
                "transcript": transcript_text[:8000],
            },
            "compliance/transcript_report",
            hint,
            context="batch",
        )
