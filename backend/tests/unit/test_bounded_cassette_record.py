"""Только MockTransport: никакой live-записи или опубликованных mock-as-live кассет."""

import copy
import json
import time

import httpx
import pytest

from app.config import Settings
from app.contracts.registry import validate_schema
from app.llm.base import LLMProfile, ProviderError
from app.llm.mock import MockProvider
from app.replay import bounded_record as br

SECRET = "synthetic-basic-key-for-unit-only"
TOKEN = "synthetic-access-token-for-unit-only"


def future_plan():
    schema = copy.deepcopy(br.build_plan()["schema"])

    def change(value):
        if isinstance(value, dict):
            if "pattern" in value and "{2,6}" in value["pattern"]:
                value["pattern"] = value["pattern"].replace("{2,6}", "{2,9}")
            for child in value.values():
                change(child)
        elif isinstance(value, list):
            for child in value:
                change(child)

    change(schema)
    plan = br.build_plan(schema)
    assert plan["record_required"]
    return plan


def settings(**overrides):
    return Settings(_env_file=None, gigachat_auth_key_1=SECRET, **overrides)


async def valid_object(plan):
    obj, _, _ = await MockProvider().complete_structured(
        plan["messages"], plan["schema"], LLMProfile(code="mock", provider="mock", model="mock-1"), timeout_s=1
    )
    assert not validate_schema(obj, plan["schema"])
    return obj


def chat_response(obj, **overrides):
    return {
        "model": br.MODEL,
        "usage": {"prompt_tokens": 3200, "completion_tokens": 700, "total_tokens": 3900},
        "choices": [{"message": {"role": "assistant", "content": json.dumps(obj, ensure_ascii=False)}}],
        **overrides,
    }


def handler(chat):
    calls = []

    def respond(request):
        calls.append(request)
        if str(request.url) == br.OAUTH_URL:
            assert request.headers["Authorization"] == f"Basic {SECRET}"
            return httpx.Response(200, json={"access_token": TOKEN, "expires_at": (time.time() + 1800) * 1000})
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
        return chat(request, len(calls) - 1)

    return calls, httpx.MockTransport(respond)


def test_plan_pins_historical_case_and_current_schema():
    plan = br.build_plan()
    assert plan["model"] == br.MODEL and plan["prompt_version"] == "v1.1"
    assert plan["record_required"] == (plan["request_hash"] != br.SOURCE_HASH)
    assert plan["initial_input_chars"] < br.MAX_INPUT_CHARS
    assert plan["limits"]["http_requests"] == 3
    assert plan["database_access"] is False
    assert future_plan()["request_hash"] != br.SOURCE_HASH


def test_dry_run_reads_no_environment_database_or_network(monkeypatch, capsys):
    def forbidden():
        raise AssertionError("settings/credentials must not be loaded")

    monkeypatch.setattr(br, "get_settings", forbidden)
    monkeypatch.setattr("sys.argv", ["bounded_record", "--dry-run"])
    br.main()
    plan = json.loads(capsys.readouterr().out)
    assert plan["messages"] == br.build_plan()["messages"]
    assert SECRET not in json.dumps(plan)


async def test_current_hash_needs_no_record_and_no_http(tmp_path):
    plan = br.build_plan()
    plan["record_required"] = False
    calls, inner = handler(lambda *_: pytest.fail("must not request"))
    status, report = await br.record(plan, settings(), tmp_path / "record", inner=inner)
    assert status == 2 and report["error"] == "no_record_required" and calls == []
    assert not (tmp_path / "record").exists()


async def test_records_only_new_response_preserving_historical_bytes_and_usage(tmp_path):
    plan = future_plan()
    old = (br.ROOT / "data/cassettes/gigachat.jsonl").read_bytes()
    obj = await valid_object(plan)
    calls, inner = handler(lambda *_: httpx.Response(200, json=chat_response(obj)))
    status, report = await br.record(plan, settings(), tmp_path / "record", inner=inner)
    assert status == 0 and report["ok"]
    assert len(calls) == 2 and report["inference_requests"] == 1 and report["oauth_requests"] == 1
    assert report["observed_completion_tokens"] == 700 and report["actual_cost_rub"] is None
    assert not report["usage_unknown"]
    saved = json.loads((tmp_path / "record/gigachat.jsonl").read_text())
    assert saved["request_hash"] == plan["request_hash"] != br.SOURCE_HASH
    assert saved["response"] == obj and saved["usage"]["source"] == "live"
    assert saved["usage"]["cost_known"] is False and "cost_rub" not in saved["usage"]
    assert saved["usage"]["total_tokens"] == 3900
    provenance = json.loads((tmp_path / "record/provenance.json").read_text())
    assert provenance["source_record_sha256"] == br.SOURCE_SHA256
    assert provenance["source_request_hash"] == br.SOURCE_HASH
    assert (br.ROOT / "data/cassettes/gigachat.jsonl").read_bytes() == old
    assert not any(secret in json.dumps(saved) + json.dumps(provenance) for secret in (SECRET, TOKEN))
    status, report = await br.record(plan, settings(), tmp_path / "record", inner=inner)
    assert status == 2 and report["error"] == "output_already_exists" and len(calls) == 2


async def test_structured_retry_is_one_key_model_two_inference_three_http_max(tmp_path):
    plan = future_plan()
    obj = await valid_object(plan)
    calls, inner = handler(lambda _request, index: httpx.Response(200, json=chat_response({} if index == 1 else obj)))
    status, report = await br.record(plan, settings(), tmp_path / "record", inner=inner)
    assert status == 0 and report["http_requests"] == 3 and report["inference_requests"] == 2
    assert report["observed_completion_tokens"] == 1400
    assert all(json.loads(request.content)["model"] == br.MODEL for request in calls[1:])
    assert all(json.loads(request.content)["max_tokens"] == 1024 for request in calls[1:])


async def test_two_invalid_structured_answers_stop_at_three_http(tmp_path):
    calls, inner = handler(lambda *_: httpx.Response(200, json=chat_response({})))
    code, report = await br.record(future_plan(), settings(), tmp_path / "record", inner=inner)
    assert code == 1 and report["error"] == "bad_output"
    assert report["http_requests"] == len(calls) == 3
    assert report["observed_completion_tokens"] == 1400 and not report["usage_unknown"]
    assert not (tmp_path / "record/gigachat.jsonl").exists()


async def test_successful_body_reflecting_secret_is_not_recorded_or_printed(tmp_path, capsys):
    plan = future_plan()
    obj = await valid_object(plan)
    obj["public_reply_ru"] = SECRET
    calls, inner = handler(lambda *_: httpx.Response(200, json=chat_response(obj)))
    code, report = await br.record(plan, settings(), tmp_path / "record", inner=inner)
    assert code == 1 and len(calls) == 2
    assert SECRET not in capsys.readouterr().out
    assert SECRET not in (tmp_path / "record/provenance.json").read_text()
    assert not (tmp_path / "record/gigachat.jsonl").exists()


async def test_transport_hard_cap_blocks_fourth_http_even_if_caller_retries():
    plan = future_plan()
    calls, inner = handler(lambda *_: httpx.Response(200, json=chat_response({})))
    guard = br.BoundedTransport(inner, plan, SECRET)
    system = br.JSON_INSTRUCTION.format(schema=json.dumps(br.schema_for_model(plan["schema"]), ensure_ascii=False))
    messages = [{"role": "system", "content": system + "\n\n" + plan["messages"][0]["content"]}, plan["messages"][1]]
    payload = {"model": br.MODEL, "messages": messages, "temperature": 0, "max_tokens": 1024, "stream": False}
    async with httpx.AsyncClient(transport=guard) as client:
        await client.post(br.OAUTH_URL, data={"scope": br.SCOPE}, headers={"Authorization": f"Basic {SECRET}"})
        await client.post(br.BASE_URL + "/chat/completions", json=payload, headers={"Authorization": f"Bearer {TOKEN}"})
        payload["messages"] = messages + [
            {"role": "assistant", "content": "{}"},
            {"role": "user", "content": "Ответ не прошёл валидацию по схеме: missing required fields"},
        ]
        await client.post(br.BASE_URL + "/chat/completions", json=payload, headers={"Authorization": f"Bearer {TOKEN}"})
        with pytest.raises(ProviderError, match="bounded_http_limit"):
            await client.post(br.OAUTH_URL, data={"scope": br.SCOPE})
    assert len(calls) == 3


async def test_second_oauth_request_is_refused_before_transport():
    calls, inner = handler(lambda *_: pytest.fail("no inference expected"))
    guard = br.BoundedTransport(inner, future_plan(), SECRET)
    request = httpx.Request(
        "POST", br.OAUTH_URL, data={"scope": br.SCOPE}, headers={"Authorization": f"Basic {SECRET}"}
    )
    await guard.handle_async_request(request)
    with pytest.raises(ProviderError, match="bounded_oauth_limit"):
        await guard.handle_async_request(request)
    assert len(calls) == 1


@pytest.mark.parametrize("status,kind", [(401, "auth"), (403, "auth"), (429, "rate_limit"), (500, "unavailable")])
async def test_http_errors_halt_without_model_or_key_fallback(tmp_path, capsys, status, kind):
    calls, inner = handler(lambda *_: httpx.Response(status, text=f"upstream reflected {SECRET} {TOKEN}"))
    code, report = await br.record(future_plan(), settings(), tmp_path / "record", inner=inner)
    assert code == 1 and report["error"] == kind and report["status"] == status
    assert len(calls) == 2 and report["inference_requests"] == 1 and report["usage_unknown"]
    assert not (tmp_path / "record/gigachat.jsonl").exists()
    assert SECRET not in capsys.readouterr().out
    assert TOKEN not in (tmp_path / "record/provenance.json").read_text()


async def test_auth_error_is_one_http_no_inference(tmp_path):
    calls = []

    def reject(request):
        calls.append(request)
        return httpx.Response(401, text=SECRET)

    code, report = await br.record(future_plan(), settings(), tmp_path / "record", inner=httpx.MockTransport(reject))
    assert code == 1 and report["error"] == "auth" and report["inference_requests"] == 0
    assert len(calls) == 1


@pytest.mark.parametrize(
    "status,text,kind",
    [
        (400, "Cannot decode Authorization", "auth"),
        (403, "quota exhausted", "quota"),
        (400, "token limit exceeded", "quota"),
    ],
)
async def test_sanitized_errors_keep_auth_and_quota_classification(tmp_path, status, text, kind):
    calls, inner = handler(lambda *_: httpx.Response(status, text=text + SECRET))
    code, report = await br.record(future_plan(), settings(), tmp_path / "record", inner=inner)
    assert code == 1 and report["error"] == kind and len(calls) == 2
    assert SECRET not in (tmp_path / "record/provenance.json").read_text()


@pytest.mark.parametrize("body", [[], {"choices": []}, {"choices": [{"message": {"content": 123}}]}])
async def test_malformed_success_is_explicit_failure_without_zero_usage_claim(tmp_path, body):
    response = body if isinstance(body, list) else chat_response({}, **body)
    calls, inner = handler(lambda *_: httpx.Response(200, json=response))
    code, report = await br.record(future_plan(), settings(), tmp_path / "record", inner=inner)
    assert code == 1 and report["error"] == "bad_output" and len(calls) == 2
    assert report["usage_unknown"] is isinstance(body, list)
    assert not (tmp_path / "record/gigachat.jsonl").exists()


@pytest.mark.parametrize("usage", [None, {}, {"prompt_tokens": True, "completion_tokens": 1, "total_tokens": 2}])
async def test_unknown_usage_is_not_zero_and_blocks_second_call(tmp_path, usage):
    plan = future_plan()
    calls, inner = handler(lambda *_: httpx.Response(200, json=chat_response({}, usage=usage)))
    code, report = await br.record(plan, settings(), tmp_path / "record", inner=inner)
    assert code == 1 and report["usage_unknown"] and len(calls) == 2
    assert not (tmp_path / "record/gigachat.jsonl").exists()


@pytest.mark.parametrize(
    "change",
    [
        {"model": "GigaChat-3-Ultra"},
        {"usage": {"prompt_tokens": 10, "completion_tokens": 1025, "total_tokens": 1035}},
        {"usage": {"prompt_tokens": 10, "completion_tokens": 1, "total_tokens": 3}},
    ],
)
async def test_upstream_wrong_model_or_token_bound_is_rejected(tmp_path, change):
    calls, inner = handler(lambda *_: httpx.Response(200, json=chat_response({}, **change)))
    code, report = await br.record(future_plan(), settings(), tmp_path / "record", inner=inner)
    assert code == 1 and report["error"] == "bad_output" and len(calls) == 2
    assert not (tmp_path / "record/gigachat.jsonl").exists()


@pytest.mark.parametrize(
    "url,method",
    [
        ("https://example.com/chat/completions", "POST"),
        (br.BASE_URL + "/models", "GET"),
        (br.BASE_URL + "/chat/completions?key=bad", "POST"),
        ("http://api.giga.chat/v1/chat/completions", "POST"),
    ],
)
async def test_transport_blocks_egress_outside_review_before_network(url, method):
    called = []
    guard = br.BoundedTransport(httpx.MockTransport(lambda r: called.append(r)), future_plan(), SECRET)
    with pytest.raises(ProviderError):
        await guard.handle_async_request(httpx.Request(method, url))
    assert not called


@pytest.mark.parametrize(
    "override",
    [
        {"max_tokens": 1025},
        {"model": "GigaChat-3-Ultra"},
        {"stream": True},
        {"messages": [{"role": "system", "content": "x" * 16_001}]},
        {"messages": [{"role": "system", "content": SECRET}]},
    ],
)
async def test_payload_bounds_and_secret_are_enforced_before_network(override):
    called = []
    guard = br.BoundedTransport(httpx.MockTransport(lambda r: called.append(r)), future_plan(), SECRET)
    payload = {"model": br.MODEL, "messages": [], "max_tokens": 1024, "stream": False, "temperature": 0, **override}
    with pytest.raises(ProviderError):
        await guard.handle_async_request(httpx.Request("POST", br.BASE_URL + "/chat/completions", json=payload))
    assert not called


@pytest.mark.parametrize(
    "override",
    [
        {"gigachat_base_url": "https://example.com"},
        {"gigachat_scope": "GIGACHAT_API_CORP"},
        {"gigachat_verify_ssl": False},
    ],
)
async def test_configuration_outside_review_fails_closed_before_creating_output(tmp_path, override):
    code, report = await br.record(future_plan(), settings(**override), tmp_path / "record")
    assert code == 2 and report["http_requests"] == 0 and report["error"] == "configuration_outside_review"
    assert not (tmp_path / "record").exists()
