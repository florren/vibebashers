"""Bounded scenario11 preparation/recording. Fake responses never become release cassettes.

CLI only prepares offline plans. Live execution is an explicitly invoked Python
API: caller supplies the reviewed primary profile/provider (durable ledger),
a separate synthetic bank and a new staging directory; it never resets a ledger.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import psycopg

from app.agent.graph import process_signal, wake_due_followups
from app.agent.prompts import prompt_version
from app.contracts.registry import deref
from app.ingest.normalizer import create_signal
from app.llm.base import LLMProfile, Message, ProviderError
from app.llm.credential_boundary import reject_reflection
from app.llm.gigachat import JSON_INSTRUCTION, GigaChatProvider, schema_for_model
from app.replay.store import CassetteStore, request_hash
from app.sim import scenarios

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "backend/tests/fixtures/replay_bank_sarcasm_v1.json"
SCENARIO = "social_sarcasm_escalation"
MODEL = "GigaChat-3-Pro"
OAUTH = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
BASE = "https://api.giga.chat/v1"
NODES = ("normalize", "classify", "decide")
SCHEMAS = ("agent/normalization", "agent/classification", "agent/decision")
LIMITS = {
    "inference_requests": 6,
    "oauth_requests": 1,
    "balance_requests": 6,
    "http_requests": 14,
    "model_catalog_requests": 1,
    "payload_bytes_per_request": 65536,
    "input_utf8_bytes_per_request": 48000,
    "input_chars_per_request": 16000,
    "output_tokens_per_request": 1024,
    "total_output_tokens": 6144,
    "overall_timeout_s": 120,
}


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def fixture() -> dict[str, Any]:
    value: dict[str, Any] = json.loads(FIXTURE.read_text())
    scenario = scenarios.get(SCENARIO)
    if scenario is None or value["text"] != scenario["inject"][0]["text"]:
        raise ValueError("scenario11_fixture_changed")
    return value


def manifest() -> dict[str, Any]:
    """No env/credentials/DB/network. Downstream requests depend on validated LLM output."""
    data = fixture()
    sources = [*sorted((ROOT / "data").glob("*.yaml")), *sorted((ROOT / "data").glob("*.csv"))]
    sources += sorted((ROOT / "backend/app/agent/prompts").glob("v*/*.md"))
    sources += [
        ROOT / name
        for name in (
            "backend/app/agent/nodes.py",
            "backend/app/replay/scenario11_record.py",
            "backend/app/llm/gigachat.py",
            "backend/app/llm/accounting.py",
            "scripts/replay11_record.py",
            "scripts/replay11_bank.py",
            "backend/tests/fixtures/replay_bank_sarcasm_v1.json",
        )
    ]
    return {
        "scenario_id": SCENARIO,
        "fixture": data,
        "fixture_sha256": digest(data),
        "model": MODEL,
        "credential_slot": "gigachat1",
        "agent_prompt_templates": "v2",
        "schema_sha256": {name: digest(deref(name)) for name in SCHEMAS},
        "source_files_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
        "limits": LIMITS,
        "endpoints": [OAUTH, BASE + "/models", BASE + "/balance", BASE + "/chat/completions"],
        "structured_attempts": 2,
        "oauth_lifecycle": "public prepare12s warms OAuth+models before graph; cached token; auth background stopped immediately",
        "provider_fallback": False,
        "tls_verification": True,
        "cost_known": False,
        "actual_cost_rub": None,
        "primary_bank_read_write": False,
        "accounting": "existing durable PostgreSQL ledger, unchanged caps; no origin/reconciliation on live",
        "request_dependency": "normalize fixed; classify/decide depend on validated earlier live output; preview hashes are NOT live hashes",
    }


def recording_profile(base: LLMProfile) -> LLMProfile:
    """Preserve all existing budget/binding fields; bound only generation settings."""
    from dataclasses import replace

    if base.provider != "gigachat" or base.model != MODEL or (base.base_url or BASE).rstrip("/") != BASE:
        raise ValueError("reviewed_gigachat_profile_required")
    return replace(
        base,
        temperature=0.0,
        extra={
            **base.extra,
            "agent_prompt_templates": "v2",
            "structured_attempts": 2,
            "oauth_lifecycle": "public prepare12s warms OAuth+models before graph; cached token; auth background stopped immediately",
            "request": {"max_tokens": LIMITS["output_tokens_per_request"]},
        },
    )


class BoundedTransport(httpx.AsyncBaseTransport):
    """Only three graph calls and their schema-correction retries may reach HTTP."""

    def __init__(self, inner: httpx.AsyncBaseTransport, *, secret: str) -> None:
        self.inner = inner
        self.secrets = [secret]
        self.counts = {"oauth": 0, "models": 0, "balance": 0, "inference": 0}
        self.expected: list[dict[str, str]] | None = None
        self.node_attempts = 0
        self.payloads: list[dict[str, Any]] = []
        self.halted = False

    def arm(self, messages: list[Message], schema: dict[str, Any]) -> None:
        if len(self.payloads) >= LIMITS["inference_requests"]:
            raise ProviderError("quota", "bounded_inference_limit")
        instruction = JSON_INSTRUCTION.format(schema=json.dumps(schema_for_model(schema), ensure_ascii=False))
        systems = [instruction, *[m["content"] for m in messages if m["role"] == "system"]]
        self.expected = [{"role": "system", "content": "\n\n".join(systems)}]
        self.expected += [{"role": m["role"], "content": m["content"]} for m in messages if m["role"] != "system"]
        self.node_attempts = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if self.halted or sum(self.counts.values()) >= LIMITS["http_requests"]:
            raise ProviderError("quota", "bounded_http_limit")
        url = str(request.url)
        if request.method == "POST" and url == OAUTH:
            if self.counts["oauth"] or request.content != b"scope=GIGACHAT_API_PERS":
                raise ProviderError("auth", "bounded_oauth_limit")
            self.counts["oauth"] += 1
        elif request.method == "GET" and url == BASE + "/models":
            if self.counts["models"] or self.counts["inference"]:
                raise ProviderError("quota", "bounded_models_limit_or_after_inference")
            self.counts["models"] += 1
        elif request.method == "GET" and url == BASE + "/balance":
            if self.counts["balance"] >= LIMITS["balance_requests"]:
                raise ProviderError("quota", "bounded_balance_limit")
            self.counts["balance"] += 1
        elif request.method == "POST" and url == BASE + "/chat/completions":
            if self.counts["inference"] >= LIMITS["inference_requests"] or self.node_attempts >= 2:
                raise ProviderError("quota", "bounded_inference_limit")
            if len(request.content) > LIMITS["payload_bytes_per_request"]:
                raise ProviderError("bad_output", "bounded_payload_bytes")
            body = json.loads(request.content)
            if set(body) != {"model", "messages", "temperature", "stream", "max_tokens"} or (
                body["model"] != MODEL
                or body["stream"] is not False
                or body["temperature"] != 0
                or body["max_tokens"] != LIMITS["output_tokens_per_request"]
            ):
                raise ProviderError("bad_output", "bounded_payload_fields")
            messages = body["messages"]
            if self.expected is None or messages[: len(self.expected)] != self.expected:
                raise ProviderError("bad_output", "bounded_messages_changed")
            suffix = messages[len(self.expected) :]
            if (not self.node_attempts and suffix) or (
                self.node_attempts
                and (
                    len(suffix) != 2
                    or [m["role"] for m in suffix] != ["assistant", "user"]
                    or not suffix[1]["content"].startswith("Ответ не прошёл валидацию по схеме: ")
                )
            ):
                raise ProviderError("bad_output", "bounded_retry_changed")
            contents = [m["content"] for m in messages]
            if (
                sum(map(len, contents)) > LIMITS["input_chars_per_request"]
                or sum(len(c.encode()) for c in contents) > LIMITS["input_utf8_bytes_per_request"]
            ):
                raise ProviderError("bad_output", "bounded_input_bytes")
            reject_reflection(body, self.secrets)
            self.payloads.append(
                {
                    "sha256": digest(body),
                    "payload_bytes": len(request.content),
                    "input_bytes": sum(len(c.encode()) for c in contents),
                    "body": body,
                }
            )
            self.node_attempts += 1
            self.counts["inference"] += 1
        else:
            raise ProviderError("unavailable", "bounded_endpoint")
        response = await self.inner.handle_async_request(request)
        await response.aread()
        if response.status_code >= 300:
            self.halted = True
            # Upstream diagnostics can reflect credentials.
            return httpx.Response(response.status_code, json={"error": "bounded_upstream_error"}, request=request)
        if url == OAUTH:
            token = response.json().get("access_token")
            if isinstance(token, str):
                self.secrets.append(token)
        else:
            reject_reflection(response.json(), self.secrets)
            if url == BASE + "/models":
                catalog = response.json()
                rows = catalog.get("data") if isinstance(catalog, dict) else None
                if not isinstance(rows, list) or not any(
                    isinstance(item, dict) and item.get("id") == MODEL for item in rows
                ):
                    raise ProviderError("bad_output", "bounded_model_not_listed")
        return response

    async def aclose(self) -> None:
        await self.inner.aclose()


class AuditedProvider:
    """Real provider + review manifest; never masquerades a replay/mock as live."""

    name = "gigachat"

    def __init__(self, provider: GigaChatProvider, transport: BoundedTransport) -> None:
        self.provider, self.transport = provider, transport
        self.accounting = provider.accounting
        self.requests: list[dict[str, Any]] = []

    async def stream(self, messages: list[Message], profile: LLMProfile, *, timeout_s: float) -> AsyncIterator[str]:
        raise ProviderError("unavailable", "bounded_streaming_forbidden")
        yield ""

    async def complete_structured(
        self, messages: list[Message], schema: dict[str, Any], profile: LLMProfile, *, timeout_s: float
    ) -> Any:
        index = len(self.requests)
        if index >= 3 or digest(schema) != manifest()["schema_sha256"][SCHEMAS[index]]:
            raise ProviderError("bad_output", "bounded_graph_order")
        if profile.extra.get("agent_prompt_templates") != "v2" or profile.extra.get("structured_attempts") != 2:
            raise ProviderError("bad_output", "bounded_profile_changed")
        self.transport.arm(messages, schema)
        self.requests.append(
            {
                "node": NODES[index],
                "request_hash": request_hash("gigachat", MODEL, messages, schema),
                "messages": messages,
                "schema": schema,
            }
        )
        return await self.provider.complete_structured(messages, schema, profile, timeout_s=timeout_s)


async def run_graph(
    conn: psycopg.AsyncConnection[Any], chain: Any, profile: LLMProfile, *, source: str
) -> dict[str, Any]:
    from app.sim.runs import create_run

    data = fixture()
    now = dt.datetime.fromisoformat(data["sim_time"])
    run_id = await create_run(
        conn, kind="scenario", label="replay11 immutable bank", seed=42, sim_time=now, scenario_id=SCENARIO
    )
    result = await create_signal(
        conn,
        {
            "channel": "social",
            "external_id": "replay11-fixed-1",
            "client": {"client_id": 1},
            "text": data["text"],
            "timestamp": data["sim_time"],
            "geo": {"source": "none"},
            "origin": "scenario",
            "meta": {"scenario_id": SCENARIO, "step": 0},
        },
        source_code="api",
        run_id=run_id,
        sim_time=now,
        emit_event=False,
    )
    if result["status"] != "accepted":
        raise ValueError("replay11_signal_not_accepted")
    await conn.commit()
    state = await process_signal(conn, signal_id=result["signal_id"], chain=chain, profile=profile, sim_time=now)
    if state is None:
        raise ValueError("replay11_no_state")
    steps = await (
        await conn.execute(
            "select node,status,model from agent_steps where run_id in(select id from agent_runs where signal_id=%s) and node=any(%s) order by seq",
            (result["signal_id"], list(NODES)),
        )
    ).fetchall()
    if [r[0] for r in steps] != list(NODES) or any(
        r[1] != "ok" or not str(r[2]).startswith(source + ":") for r in steps
    ):
        raise ValueError("strict_replay11_llm_steps_failed")
    delivery = await (
        await conn.execute(
            "select count(*) from notifications where run_id=%s and signal_id=%s and template_code='clarify_request' and status in ('sent','delivered') and sent_at is not null",
            (run_id, result["signal_id"]),
        )
    ).fetchone()
    if not delivery or delivery[0] != 1:
        raise ValueError("replay11_missing_sent_clarification")
    due = await (
        await conn.execute(
            "select max(wake_sim) from followups where signal_id=%s and reason='awaiting_client' and status='scheduled'",
            (result["signal_id"],),
        )
    ).fetchone()
    if not due or not due[0]:
        raise ValueError("replay11_missing_clarification_followup")
    woken = await wake_due_followups(conn, sim_time=due[0], chain=chain, profile=profile, signal_id=result["signal_id"])
    if woken != 1:
        raise ValueError("replay11_followup_not_executed")
    escalation = await (
        await conn.execute(
            "select count(*) from escalations where run_id=%s and signal_id=%s and to_role='cx_lead'",
            (run_id, result["signal_id"]),
        )
    ).fetchone()
    if not escalation or escalation[0] != 1:
        raise ValueError("replay11_missing_actual_escalation")
    scenario = scenarios.get(SCENARIO)
    assert scenario is not None
    evaluation = await scenarios.evaluate(conn, scenario, run_id)
    if evaluation["counts"]["errors"] or any(c["ok"] is False for c in evaluation["checks"]):
        raise ValueError("replay11_acceptance_failed")
    await conn.commit()
    return {"run_id": run_id, "signal_id": result["signal_id"], "steps": steps, "evaluation": evaluation}


async def record(
    conn: psycopg.AsyncConnection[Any],
    provider: GigaChatProvider,
    transport: BoundedTransport,
    profile: LLMProfile,
    staging: Path,
    *,
    fake_transport: bool = False,
) -> dict[str, Any]:
    """Staging only. Caller must explicitly authorize egress before supplying a live transport."""
    from app.llm.failover import ProviderChain

    if provider._client._transport is not transport:
        raise ValueError("reviewed_transport_identity_required")
    if not provider.accounting.durable:
        raise ValueError("durable_accounting_required")
    if len(provider.pool.keys) != 1 or (not fake_transport and provider.pool.keys[0].label != "gigachat_env_1"):
        raise ValueError("reviewed_credential_slot_required")
    if profile.api_key_id is not None or profile.temperature != 0:
        raise ValueError("reviewed_env_profile_required")
    staging.mkdir(parents=True, exist_ok=False)
    store = CassetteStore(staging / ("FAKE-DO-NOT-PUBLISH" if fake_transport else "cassettes"))
    audited = AuditedProvider(provider, transport)
    chain = ProviderChain(
        [audited],
        append_mock=False,
        record_store=store,
        scenario_id=SCENARIO,
        prompt_version=prompt_version(),
    )
    profile = recording_profile(profile)
    try:
        result = await run_graph(conn, chain, profile, source="gigachat")
        report = {
            "status": "PASS",
            "fake_transport": fake_transport,
            "manifest": manifest(),
            "requests": audited.requests,
            "http_counts": transport.counts,
            "payloads": transport.payloads,
            "graph": result,
        }
    except BaseException as exc:
        (staging / "failure.json").write_text(
            json.dumps(
                {
                    "status": "FAIL",
                    "error_type": type(exc).__name__,
                    "fake_transport": fake_transport,
                    "http_counts": transport.counts,
                },
                ensure_ascii=False,
            )
        )
        raise
    (staging / "provenance.json").write_text(json.dumps(report, ensure_ascii=False, default=str, indent=2))
    return report
