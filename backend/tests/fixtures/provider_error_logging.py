"""Synthetic-only SDK/HTTP error boundary: настоящий console + JSONL, без сети."""

import asyncio
import json
import logging
import sys
import traceback
from pathlib import Path

import httpx

from app.llm.base import LLMProfile, ProviderError
from app.llm.gigachat import GigaChatProvider
from app.llm.keys import ApiKey, KeyPool
from app.llm.openai_compat import _SDK_LOGGERS, OpenAICompatProvider
from app.logging import configure_logging, get_logger

SECRET = "synthetic-upstream-exception-credential"
mode, jsonl_path = sys.argv[1], Path(sys.argv[2])
configure_logging("prod", jsonl_path, "debug")
logger = get_logger("synthetic-provider-errors")
calls = []
root_level = logging.getLogger().level
httpx_level = logging.getLogger("httpx").level


def handler(request):
    calls.append(request.url.path)
    if mode.endswith("network"):
        raise httpx.ReadError(SECRET, request=request)
    if mode.endswith("json"):
        return httpx.Response(200, content=("invalid-json-" + SECRET).encode())
    return httpx.Response(500, json={"error": {"message": SECRET}}, headers={"X-Synthetic-Echo": SECRET})


async def run():
    if mode.startswith("sdk"):
        # OPENAI_LOG=debug был прочитан SDK до создания owned client.
        assert logging.getLogger("openai").getEffectiveLevel() < logging.WARNING
        provider = OpenAICompatProvider(SECRET, "https://synthetic.invalid/v1", transport=httpx.MockTransport(handler))
        assert all(logging.getLogger(name).getEffectiveLevel() >= logging.WARNING for name in _SDK_LOGGERS)
        if mode != "sdk_json":
            # Повторное SDK logging setup не должно обойти следующий wire boundary.
            for name in _SDK_LOGGERS:
                logging.getLogger(name).setLevel(logging.DEBUG)
    else:
        provider = GigaChatProvider(
            KeyPool([ApiKey("synthetic-label", SECRET)]),
            oauth_url="https://synthetic.invalid/oauth",
            base_url="https://synthetic.invalid/v1",
            transport=httpx.MockTransport(handler),
        )
    try:
        try:
            if mode == "sdk_json":
                await provider.fetch_key()
            else:
                await provider.complete_structured(
                    [{"role": "user", "content": "fixed synthetic"}],
                    {"type": "object"},
                    LLMProfile(code="synthetic", provider=provider.name, model="synthetic:free"),
                    timeout_s=1,
                )
        except ProviderError as error:
            assert SECRET not in "".join(traceback.format_exception(error))
            logger.exception("synthetic_provider_failure", kind=error.kind, status=error.status)
        else:
            raise AssertionError("fake failure must not return success")
        assert len(calls) == 1
        assert logging.getLogger().level == root_level
        assert logging.getLogger("httpx").level == httpx_level
    finally:
        await provider.aclose()
    assert SECRET not in jsonl_path.read_text()
    sys.stdout.write(json.dumps({"calls": len(calls), "safe": True}) + "\n")


asyncio.run(run())
