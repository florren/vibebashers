"""Ограниченный синтетический smoke OpenRouter, запуск только после ревью egress.

python -m app.llm.live_smoke --run
До 3 фиксированных моделей, до 6 HTTP запросов всего (/key включён), до 128
output tokens на completion. Вход фиксирован, реальных ПДн нет. Ключ/ответы/URL
в отчёт не выводятся; failure не заменяется mock-успехом.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from functools import partial
from typing import Any

import httpx

from app.config import get_settings
from app.contracts.registry import deref
from app.llm.base import LLMProfile, ProviderError
from app.llm.budget import load_openrouter_budget
from app.llm.openai_compat import DEFAULT_MODEL_IDS, OpenAICompatProvider

FIXED_TEXT = "В приложении Банка не открывается вклад. Прошу помочь."
MAX_REQUESTS = 6
MAX_OUTPUT_TOKENS = 128
BASE_URL = "https://openrouter.ai/api/v1"


class BoundedTransport(httpx.AsyncBaseTransport):
    def __init__(self, inner: httpx.AsyncBaseTransport) -> None:
        self.inner = inner
        self.requests = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        allowed = (
            request.url.scheme == "https"
            and request.url.host == "openrouter.ai"
            and request.url.port in (None, 443)
            and not request.url.query
            and not request.url.username
            and not request.url.password
            and (request.method, request.url.path) in (("GET", "/api/v1/key"), ("POST", "/api/v1/chat/completions"))
        )
        if not allowed or self.requests >= MAX_REQUESTS:
            raise httpx.RequestError("Запрос запрещён ограничениями synthetic smoke", request=request)
        if request.method == "POST":
            payload = json.loads(request.content)
            if (
                payload.get("model") not in DEFAULT_MODEL_IDS
                or payload.get("max_tokens") != MAX_OUTPUT_TOKENS
                or payload.get("stream") is not False
                or [message["content"] for message in payload["messages"] if message["role"] == "user"][0] != FIXED_TEXT
            ):
                raise httpx.RequestError("Payload вне согласованных границ synthetic smoke", request=request)
        self.requests += 1
        return await self.inner.handle_async_request(request)

    async def aclose(self) -> None:
        await self.inner.aclose()


async def run() -> tuple[int, dict[str, Any]]:
    settings = get_settings()
    if not settings.openrouter_api_key:
        return 2, {"ok": False, "error": "OPENROUTER_API_KEY не задан", "http_requests": 0}
    # SDK не должен печатать request body/headers даже при OPENAI_LOG=debug.
    logging.getLogger("openai").setLevel(logging.CRITICAL)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    transport = BoundedTransport(httpx.AsyncHTTPTransport(retries=0))
    provider = OpenAICompatProvider(
        settings.openrouter_api_key,
        BASE_URL,
        transport=transport,
        http_referer=f"http://localhost:{settings.app_port}",
        budget_usd=settings.openrouter_budget_usd,
        budget_loader=partial(load_openrouter_budget, settings.openrouter_budget_usd),
    )
    results = []
    try:
        for model in DEFAULT_MODEL_IDS:
            if transport.requests >= MAX_REQUESTS:
                results.append({"model": model, "ok": False, "error": "http_request_budget"})
                continue
            profile = LLMProfile(
                code="bounded_smoke",
                provider="openai_compatible",
                model=model,
                extra={"max_output_tokens": MAX_OUTPUT_TOKENS},
            )
            try:
                _obj, usage, _raw = await provider.complete_structured(
                    [{"role": "user", "content": FIXED_TEXT}], deref("agent/classification"), profile, timeout_s=15
                )
                results.append(
                    {
                        "model": model,
                        "ok": True,
                        "prompt_tokens": usage.prompt_tokens,
                        "completion_tokens": usage.completion_tokens,
                    }
                )
            except ProviderError as exc:
                results.append({"model": model, "ok": False, "error": exc.kind, "status": exc.status})
    finally:
        await provider.aclose()
    report = {
        "ok": all(result["ok"] for result in results),
        "synthetic": True,
        "models": results,
        "http_requests": transport.requests,
        "max_output_tokens_per_request": MAX_OUTPUT_TOKENS,
    }
    return (0 if report["ok"] else 1), report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="Выполнить ограниченный egress после его согласования")
    if not parser.parse_args().run:
        parser.error("для сетевого smoke требуется явный --run; сначала согласуйте egress")
    status, report = asyncio.run(run())
    sys.stdout.write(json.dumps(report, ensure_ascii=False) + "\n")
    raise SystemExit(status)


if __name__ == "__main__":
    main()
