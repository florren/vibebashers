"""Schema-derived repair feedback keeps validation strict and the first request unchanged."""

import copy
import json
import time

import httpx
import pytest

from app.contracts.registry import validate_schema
from app.llm.base import LLMProfile
from app.llm.gigachat import GigaChatProvider
from app.llm.keys import ApiKey, KeyPool


@pytest.mark.parametrize(
    "constraint,value,invalid",
    [
        ("minItems", 2, []),
        ("maxItems", 1, ["a", "b"]),
        ("minLength", 2, "a"),
        ("maxLength", 1, "ab"),
        ("minProperties", 2, {}),
        ("maxProperties", 1, {"a": 1, "b": 2}),
    ],
)
def test_constraint_feedback_is_opt_in_and_does_not_repair_values(constraint, value, invalid):
    schema = {"type": "object", "properties": {"field": {constraint: value}}}
    obj = {"field": invalid}
    before = copy.deepcopy((obj, schema))
    ordinary = validate_schema(obj, schema)
    detailed = validate_schema(obj, schema, with_constraints=True)
    assert ordinary and len(ordinary) == len(detailed)
    assert detailed == [f"{ordinary[0]} [{constraint}={value}]"]
    assert (obj, schema) == before
    assert validate_schema(obj, schema) == ordinary


def test_conditional_human_options_explains_minimum_at_its_actual_path():
    schema = {
        "type": "object",
        "properties": {"needs_human": {"type": "boolean"}, "human_options": {"type": "array"}},
        "allOf": [
            {
                "if": {"properties": {"needs_human": {"const": True}}},
                "then": {"properties": {"human_options": {"minItems": 2}}},
            }
        ],
    }
    errors = validate_schema({"needs_human": True, "human_options": ["accept"]}, schema, with_constraints=True)
    assert len(errors) == 1 and errors[0].startswith("human_options:") and errors[0].endswith("[minItems=2]")
    assert validate_schema({"needs_human": False, "human_options": []}, schema, with_constraints=True) == []


@pytest.mark.parametrize("model", ["GigaChat-3-Lightning", "GigaChat-3-Ultra", "GigaChat-3-Pro"])
async def test_actual_sdk_repairs_minimum_on_second_call_without_mutating_initial_messages(model):
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"options": {"type": "array", "items": {"type": "string"}, "minItems": 2}},
        "required": ["options"],
    }
    messages = [{"role": "user", "content": "Synthetic schema repair check"}]
    original = copy.deepcopy(messages)
    calls = []

    def http(request):
        if request.url.path == "/oauth":
            return httpx.Response(
                200, json={"access_token": "synthetic-repair-access", "expires_at": (time.time() + 3600) * 1000}
            )
        payload = json.loads(request.content)
        calls.append(payload)
        corrected = "minItems=2" in payload["messages"][-1]["content"]
        return httpx.Response(
            200,
            json={
                "model": model + ":synthetic",
                "choices": [{"message": {"content": json.dumps({"options": ["a", "b"] if corrected else []})}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2},
            },
        )

    provider = GigaChatProvider(
        KeyPool([ApiKey("synthetic", "synthetic-schema-repair")]),
        oauth_url="https://repair.invalid/oauth",
        base_url="https://repair.invalid/v1",
        transport=httpx.MockTransport(http),
    )
    try:
        obj, usage, _ = await provider.complete_structured(
            messages, schema, LLMProfile("repair", "gigachat", model), timeout_s=30
        )
        assert obj == {"options": ["a", "b"]} and validate_schema(obj, schema) == []
        assert len(calls) == 2 and usage.request_count == 2 and usage.total_tokens == 10
        assert messages == original
        assert "minItems=2" not in calls[0]["messages"][-1]["content"]
        assert "options:" in calls[1]["messages"][-1]["content"]
        assert "minItems=2" in calls[1]["messages"][-1]["content"]
    finally:
        await provider.aclose()
