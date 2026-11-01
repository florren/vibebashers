"""T-198: фиксированный synthetic instant-case; dry-run без env/БД/сети.

Live --run требует отдельного egress review. Старые ответы не rekeyed: запись
содержит только новый ответ на текущую schema, в отдельном staging-каталоге.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import httpx

from app.config import Settings, get_settings
from app.contracts.registry import deref
from app.llm.base import LLMProfile, ProviderError
from app.llm.gigachat import JSON_INSTRUCTION, GigaChatProvider, _bad_authorization, schema_for_model
from app.llm.keys import ApiKey, KeyPool
from app.llm.tls import context as tls_context
from app.replay.store import CassetteStore, request_hash

ROOT = Path(__file__).resolve().parents[3]
MODEL = "GigaChat-3-Pro"
SCENARIO = "qr_fee_public_review"
VERSION = "v1.1"
SOURCE_HASH = "174508311da29178f016ba3094e36291612a740c37427ff51ec4dedeede099a0"
SOURCE_SHA256 = "9fa6dbc1585c3c6bf251c7774779f5f9e6da467ba1ea26f42e792cb82aef03ed"
OAUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
BASE_URL = "https://api.giga.chat/v1"
SCOPE = "GIGACHAT_API_PERS"
MAX_INPUT_CHARS = 16_000
MAX_INPUT_BYTES = 48_000
MAX_PAYLOAD_BYTES = 64_000
MAX_OUTPUT_TOKENS = 1024
MAX_HTTP = 3
MAX_INFERENCE = 2
TIMEOUT_S = 30
OUTPUT = ROOT / "var/recordings/T-198"


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def build_plan(schema: dict[str, Any] | None = None) -> dict[str, Any]:
    """Только pinned historical messages; historical response никогда не становится новым."""
    fixture = json.loads((ROOT / "backend/tests/fixtures/replay_bank_v1.json").read_text())
    if fixture["source_request_hash"] != SOURCE_HASH:
        raise ValueError("frozen_bank_changed")
    records = [
        json.loads(line) for line in (ROOT / "data/cassettes/gigachat.jsonl").read_text().splitlines() if line.strip()
    ]
    source = next(record for record in records if record["request_hash"] == SOURCE_HASH)
    if digest(source) != SOURCE_SHA256:
        raise ValueError("source_record_changed")
    if (source["provider"], source["model"], source["scenario_id"], source["prompt_version"]) != (
        "gigachat",
        MODEL,
        SCENARIO,
        VERSION,
    ):
        raise ValueError("source_case_changed")
    schema = deref("agent/instant_decision") if schema is None else schema
    messages = source["messages"]
    target = request_hash("gigachat", MODEL, messages, schema)
    instruction = JSON_INSTRUCTION.format(schema=json.dumps(schema_for_model(schema), ensure_ascii=False))
    wire_messages = [{"role": "system", "content": instruction + "\n\n" + messages[0]["content"]}, messages[1]]
    chars = sum(len(message["content"]) for message in wire_messages)
    input_bytes = sum(len(message["content"].encode()) for message in wire_messages)
    payload_bytes = len(
        json.dumps(
            {
                "model": MODEL,
                "messages": wire_messages,
                "temperature": 0.0,
                "stream": False,
                "max_tokens": MAX_OUTPUT_TOKENS,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
    )
    if chars > MAX_INPUT_CHARS or input_bytes > MAX_INPUT_BYTES or payload_bytes > MAX_PAYLOAD_BYTES:
        raise ValueError("initial_input_limit")
    return {
        "scenario_id": SCENARIO,
        "model": MODEL,
        "prompt_version": VERSION,
        "source_request_hash": SOURCE_HASH,
        "source_record_sha256": SOURCE_SHA256,
        "source_recorded_at": source["recorded_at"],
        "frozen_bank_sha256": digest(fixture),
        "schema_sha256": digest(schema),
        "request_hash": target,
        "record_required": target != SOURCE_HASH,
        "messages": messages,
        "wire_messages": wire_messages,
        "schema": schema,
        "initial_input_chars": chars,
        "initial_input_utf8_bytes": input_bytes,
        "initial_payload_utf8_bytes": payload_bytes,
        "limits": {
            "http_requests": MAX_HTTP,
            "oauth_requests": 1,
            "inference_requests": MAX_INFERENCE,
            "input_chars_per_request": MAX_INPUT_CHARS,
            "input_utf8_bytes_per_request": MAX_INPUT_BYTES,
            "payload_bytes_per_request": MAX_PAYLOAD_BYTES,
            "output_tokens_per_request": MAX_OUTPUT_TOKENS,
            "total_output_tokens": MAX_OUTPUT_TOKENS * MAX_INFERENCE,
            "total_generation_timeout_s": TIMEOUT_S,
        },
        "endpoints": [OAUTH_URL, BASE_URL + "/chat/completions"],
        "scope": SCOPE,
        "database_access": False,
    }


class BoundedTransport(httpx.AsyncBaseTransport):
    """Капы применяются до inner transport, включая retry самого провайдера."""

    def __init__(self, inner: httpx.AsyncBaseTransport, plan: dict[str, Any], secret: str) -> None:
        self.inner, self.plan = inner, plan
        self.secrets = {secret}
        self.oauth = self.inference = 0
        self.halted = False
        self.usage: list[dict[str, int]] = []
        self.usage_unknown = False

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if self.halted or self.oauth + self.inference >= MAX_HTTP or request.method != "POST":
            raise ProviderError("quota", "bounded_http_limit")
        if url == OAUTH_URL:
            if self.oauth or request.content != b"scope=GIGACHAT_API_PERS":
                raise ProviderError("auth", "bounded_oauth_limit")
            self.oauth += 1
        elif url == BASE_URL + "/chat/completions":
            if self.inference >= MAX_INFERENCE or len(request.content) > MAX_PAYLOAD_BYTES:
                raise ProviderError("quota", "bounded_inference_limit")
            payload = json.loads(request.content)
            if set(payload) != {"model", "messages", "temperature", "stream", "max_tokens"} or (
                payload["model"] != MODEL
                or payload["stream"] is not False
                or payload["max_tokens"] != MAX_OUTPUT_TOKENS
                or payload["temperature"] != 0
            ):
                raise ProviderError("bad_output", "bounded_payload_changed")
            messages = payload["messages"]
            contents = [message["content"] for message in messages]
            if (
                sum(map(len, contents)) > MAX_INPUT_CHARS
                or sum(len(content.encode()) for content in contents) > MAX_INPUT_BYTES
                or any(secret and secret in request.content.decode() for secret in self.secrets)
            ):
                raise ProviderError("bad_output", "bounded_input_limit_or_secret")
            # Первый запрос — строго утверждённые сообщения + текущая schema.
            if messages[:2] != self.plan["wire_messages"]:
                raise ProviderError("bad_output", "frozen_input_changed")
            if len(messages) != (2 if self.inference == 0 else 4) or (
                self.inference
                and (
                    [message["role"] for message in messages[2:]] != ["assistant", "user"]
                    or not messages[3]["content"].startswith("Ответ не прошёл валидацию по схеме: ")
                )
            ):
                raise ProviderError("bad_output", "bounded_retry_changed")
            self.inference += 1
            self.usage_unknown = True
        else:
            raise ProviderError("unavailable", "bounded_endpoint")
        response = await self.inner.handle_async_request(request)
        await response.aread()
        if response.status_code >= 300:
            self.halted = True
            self.usage_unknown = self.inference > len(self.usage)
            # upstream error не должен отражать credentials в logger провайдера.
            marker = "bounded_upstream_failure"
            if _bad_authorization(response.status_code, response.text):
                marker = "authorization"
            elif response.status_code == 403 and "quota" in response.text.lower():
                marker = "quota"
            elif response.status_code == 400 and "token" in response.text.lower() and "limit" in response.text.lower():
                marker = "token limit"
            return httpx.Response(response.status_code, json={"error": marker}, request=request)
        body = response.json()
        if not isinstance(body, dict):
            self.halted = True
            raise ProviderError("bad_output", "invalid_upstream_json_object")
        if url == OAUTH_URL:
            token = body.get("access_token")
            if not isinstance(token, str) or not token:
                self.halted = True
                raise ProviderError("auth", "invalid_oauth_response")
            self.secrets.add(token)
        else:
            usage = body.get("usage")
            if not isinstance(usage, dict) or any(
                not isinstance(usage.get(key), int) or isinstance(usage[key], bool) or usage[key] < 0
                for key in ("prompt_tokens", "completion_tokens", "total_tokens")
            ):
                self.halted = self.usage_unknown = True
                raise ProviderError("bad_output", "unknown_usage")
            self.usage.append({key: usage[key] for key in ("prompt_tokens", "completion_tokens", "total_tokens")})
            self.usage_unknown = False
            if (
                usage["completion_tokens"] > MAX_OUTPUT_TOKENS
                or usage["total_tokens"] != (usage["prompt_tokens"] + usage["completion_tokens"])
                or str(body.get("model", "")).split(":")[0] != MODEL
            ):
                self.halted = True
                raise ProviderError("bad_output", "upstream_model_or_usage_bound")
            if any(secret and secret in json.dumps(body, ensure_ascii=False) for secret in self.secrets):
                self.halted = True
                raise ProviderError("bad_output", "upstream_secret_reflection")
            choices = body.get("choices")
            if (
                not isinstance(choices, list)
                or not choices
                or not isinstance(choices[0], dict)
                or not isinstance(choices[0].get("message"), dict)
                or not isinstance(choices[0]["message"].get("content"), str)
            ):
                self.halted = True
                raise ProviderError("bad_output", "invalid_upstream_choices")
        return response

    async def aclose(self) -> None:
        await self.inner.aclose()

    def report(self) -> dict[str, Any]:
        return {
            "http_requests": self.oauth + self.inference,
            "oauth_requests": self.oauth,
            "inference_requests": self.inference,
            "usage_unknown": self.usage_unknown,
            "observed_prompt_tokens": sum(usage["prompt_tokens"] for usage in self.usage),
            "observed_completion_tokens": sum(usage["completion_tokens"] for usage in self.usage),
            "actual_cost_rub": None,
        }


async def record(
    plan: dict[str, Any],
    settings: Settings,
    output: Path,
    *,
    inner: httpx.AsyncBaseTransport | None = None,
) -> tuple[int, dict[str, Any]]:
    if not plan["record_required"] or plan["request_hash"] == SOURCE_HASH:
        return 2, {"ok": False, "error": "no_record_required", "http_requests": 0}
    if not settings.gigachat_auth_key_1:
        return 2, {"ok": False, "error": "GIGACHAT_AUTH_KEY_1_required", "http_requests": 0}
    if (settings.gigachat_base_url.rstrip("/"), settings.gigachat_oauth_url, settings.gigachat_scope) != (
        BASE_URL,
        OAUTH_URL,
        SCOPE,
    ) or not settings.gigachat_verify_ssl:
        return 2, {"ok": False, "error": "configuration_outside_review", "http_requests": 0}
    try:
        output.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        return 2, {"ok": False, "error": "output_already_exists", "http_requests": 0}
    guard = BoundedTransport(
        inner
        or httpx.AsyncHTTPTransport(verify=tls_context(settings.gigachat_ca_bundle_file), retries=0, trust_env=False),
        plan,
        settings.gigachat_auth_key_1,
    )
    provider = GigaChatProvider(
        KeyPool([ApiKey(label="bounded_record", secret=settings.gigachat_auth_key_1)]),
        oauth_url=OAUTH_URL,
        base_url=BASE_URL,
        scope=SCOPE,
        ca_bundle_file=settings.gigachat_ca_bundle_file,
        transport=guard,
    )
    profile = LLMProfile(
        code="bounded_record",
        provider="gigachat",
        model=MODEL,
        extra={"structured_attempts": 2, "request": {"max_tokens": MAX_OUTPUT_TOKENS}},
    )
    report: dict[str, Any] = {"ok": False, "request_hash": plan["request_hash"]}
    try:
        async with asyncio.timeout(TIMEOUT_S + 5):
            obj, usage, _raw = await provider.complete_structured(
                plan["messages"],
                plan["schema"],
                profile,
                timeout_s=TIMEOUT_S,
            )
        # Локальный zero-price profile не является доказательством бесплатного расхода.
        usage_data = {key: value for key, value in usage.as_dict().items() if key not in ("cost_rub", "key_label")}
        usage_data["cost_known"] = False
        store = CassetteStore(output)
        store.record(
            "gigachat",
            MODEL,
            plan["messages"],
            plan["schema"],
            response=obj,
            usage=usage_data,
            scenario_id=SCENARIO,
            prompt_version=VERSION,
        )
        report["ok"] = True
    except ProviderError as exc:
        report.update(error=exc.kind, status=exc.status)
    except (TimeoutError, httpx.HTTPError, ValueError, KeyError, TypeError):
        report["error"] = "invalid_or_incomplete_upstream_response"
    finally:
        await provider.aclose()
    report.update(guard.report())
    provenance = {
        **{key: value for key, value in plan.items() if key not in ("messages", "wire_messages", "schema")},
        **report,
    }
    (output / "provenance.json").write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + "\n")
    return (0 if report["ok"] else 1), report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="Только после отдельного human egress review")
    parser.add_argument(
        "--dry-run", action="store_true", help="Показать точные synthetic input/schema; без env/БД/сети"
    )
    args = parser.parse_args()
    if args.run and args.dry_run:
        parser.error("--run и --dry-run несовместимы")
    plan = build_plan()
    if not args.run:
        sys.stdout.write(json.dumps(plan, ensure_ascii=False, indent=2) + "\n")
        return
    if not plan["record_required"] or plan["request_hash"] == SOURCE_HASH:
        sys.stdout.write(json.dumps({"ok": False, "error": "no_record_required", "http_requests": 0}) + "\n")
        raise SystemExit(2)
    status, report = asyncio.run(record(plan, get_settings(), OUTPUT))
    sys.stdout.write(json.dumps(report, ensure_ascii=False) + "\n")
    raise SystemExit(status)


if __name__ == "__main__":
    main()
