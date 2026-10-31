"""Live-бенчмарк штатного normalization-промпта; без создания сигналов и изменения БД.

Запускается с окружением backend. Ключи читаются только через Settings. Цепочка
строгая: mock/replay исключены, превышение бюджета считается ошибкой.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import psycopg
from app.agent.nodes import _llm, regex_hints
from app.config import get_settings
from app.db.session import psycopg_dsn
from app.llm.base import ProviderError
from app.llm.failover import ProviderChain, build_chain
from app.llm.roles import select
from psycopg.rows import dict_row


async def run(dataset: Path, output: Path, limits: list[float], context: str) -> None:
    if any(not math.isfinite(x) or not 0 < x <= 30 for x in limits):
        raise ValueError("Бюджет должен быть в диапазоне (0,30] секунд")
    cases = json.loads(dataset.read_text())
    if not 10 <= len(cases) <= 20:
        raise ValueError("Нужен набор из 10–20 кейсов")
    settings = get_settings()
    configured = build_chain(settings)
    providers = [p for p in configured.providers if p.name == "gigachat"]
    if not providers:
        raise ValueError("GigaChat не настроен")
    async with await psycopg.AsyncConnection.connect(psycopg_dsn(), row_factory=dict_row) as conn:
        rows = await (await conn.execute("select * from llm_profiles")).fetchall()
        saved = await (await conn.execute("select value from settings where key='setup_payload'")).fetchone()
    profiles = select(settings, list(rows), ((saved or {}).get("value") or {}).get("llm") or {})
    if profiles["fast"].provider != "gigachat":
        raise ValueError("Быстрая роль должна использовать GigaChat")
    results = []
    try:
        for index, case in enumerate(cases):
            # Порядок бюджетов чередуется, провайдер/кэш OAuth общий на весь прогон.
            for limit in limits if index % 2 == 0 else list(reversed(limits)):
                chain = ProviderChain(providers, append_mock=False, timeouts={context: limit})
                chain.role_profiles = profiles
                deps = SimpleNamespace(chain=chain, profile=profiles["main"])
                start = time.perf_counter()
                result = {"case": case["id"], "limit_s": limit, "chars": len(case["text"])}
                try:
                    obj, meta = await _llm(
                        deps,
                        "normalize",
                        "agent/normalization",
                        {"hints": regex_hints(case["text"]), "channel": case["channel"], "text": case["text"]},
                        case["text"],
                        profile=profiles["fast"],
                        context=context,
                        fallback_profile=profiles["main"],
                    )
                    result.update(
                        ok=True,
                        provider=meta["provider"],
                        model=meta["model"],
                        tokens=meta["usage"]["total_tokens"],
                        attempts=meta["attempts"],
                        sentiment=obj.get("sentiment"),
                    )
                except ProviderError as exc:
                    result.update(ok=False, error_kind=exc.kind)
                result["elapsed_ms"] = round((time.perf_counter() - start) * 1000)
                results.append(result)
                output.write_text(json.dumps(results, ensure_ascii=False, indent=2))
                sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
                sys.stdout.flush()
    finally:
        for provider in configured.providers:
            close = getattr(provider, "aclose", None)
            if close:
                await close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limits", type=float, nargs="+", default=[8, 10])
    parser.add_argument("--context", choices=["normalization", "fast_path"], default="normalization")
    args = parser.parse_args()
    asyncio.run(run(args.dataset, args.output, args.limits, args.context))
