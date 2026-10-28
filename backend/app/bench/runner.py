"""Бенчмарк-раннер classify по JSONL-наборам (T-129, ТЗ §14.2–14.3, §5.2). Без записи в БД."""

from __future__ import annotations

import argparse
import asyncio
import csv
import io
import json
import sys
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from app.agent.prompts import load as load_prompt
from app.bench.metrics import aggregate
from app.contracts.enums import Team
from app.contracts.registry import deref, validate_schema
from app.llm.base import LLMProfile, Message, ProviderError
from app.llm.failover import ProviderChain
from app.llm.mock import MockProvider
from app.llm.ratelimit import RateLimiter
from app.logging import get_logger

log = get_logger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[3]
BENCH_DIR = REPO_ROOT / "data" / "bench"
GOLDEN_DIR = REPO_ROOT / "data" / "golden"

TEAMS_PLACEHOLDER = ", ".join(t.value for t in Team)


@dataclass(slots=True)
class BenchCase:
    case_id: int
    external_id: str
    channel: str
    text: str
    gold: dict[str, Any]


@dataclass(slots=True)
class Forecast:
    est_tokens: int
    est_requests: int
    fits_limits: bool
    warning: str = ""


@dataclass
class BenchRunRecord:
    id: int
    dataset_code: str
    llm_profile_code: str
    prompt_version: str
    seed: int | None
    repeats: int
    status: Literal["queued", "running", "done", "failed", "cancelled"]
    metrics: dict[str, Any] | None = None
    progress: float = 0.0
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    results: list[dict[str, Any]] = field(default_factory=list)
    _cancel: bool = field(default=False, repr=False)

    def request_cancel(self) -> None:
        self._cancel = True


_RUNS: dict[int, BenchRunRecord] = {}
_NEXT_RUN_ID = 1


def dataset_path(code: str) -> Path:
    for folder in (BENCH_DIR, GOLDEN_DIR):
        path = folder / f"{code}.jsonl"
        if path.is_file():
            return path
    return BENCH_DIR / f"{code}.jsonl"


def list_datasets() -> list[dict[str, Any]]:
    found: dict[str, Path] = {}
    for folder in (BENCH_DIR, GOLDEN_DIR):
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.jsonl")):
            found.setdefault(path.stem, path)
    rows = []
    for i, (code, path) in enumerate(sorted(found.items()), start=1):
        n = sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
        rows.append({"id": i, "code": code, "title_ru": code, "cases": n})
    return rows


def dataset_code_by_id(dataset_id: int) -> str:
    rows = list_datasets()
    for row in rows:
        if row["id"] == dataset_id:
            return str(row["code"])
    raise FileNotFoundError(f"набор id={dataset_id} не найден")


def load_dataset(code: str) -> list[BenchCase]:
    path = dataset_path(code)
    if not path.is_file():
        raise FileNotFoundError(f"набор {code!r} не найден: {path}")
    cases: list[BenchCase] = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        row = json.loads(line)
        cases.append(
            BenchCase(
                case_id=len(cases) + 1,
                external_id=str(row.get("id") or f"case-{i}"),
                channel=str(row["channel"]),
                text=str(row["text"]),
                gold=dict(row["gold"]),
            )
        )
    return cases


def build_classify_prompt(case: BenchCase) -> str:
    return load_prompt("classify").render(
        text=case.text,
        teams=TEAMS_PLACEHOLDER,
        fewshot="",
        context="",
        normalization="",
        channel=case.channel,
    )


def compute_correct(gold: dict[str, Any], predicted: dict[str, Any]) -> dict[str, bool]:
    correct: dict[str, bool] = {}
    if "signal_type" in gold:
        correct["signal_type"] = predicted.get("signal_type") == gold["signal_type"]
    if "product" in gold:
        correct["product"] = predicted.get("product") == gold["product"]
    if "system" in gold:
        correct["system"] = predicted.get("system") == gold["system"]
    if "criticality" in gold:
        correct["criticality"] = predicted.get("criticality") == gold["criticality"]
    if "team" in gold:
        ps_raw = predicted.get("problem_summary")
        ps = ps_raw if isinstance(ps_raw, dict) else {}
        correct["team"] = ps.get("suggested_team") == gold["team"]
    return correct


def forecast(
    dataset_code: str,
    profile: LLMProfile,
    *,
    repeats: int = 1,
    key_tokens_remaining: int | None = None,
    cases: list[BenchCase] | None = None,
) -> Forecast:
    cases = load_dataset(dataset_code) if cases is None else cases
    if not cases:
        return Forecast(est_tokens=0, est_requests=0, fits_limits=True)
    prompts = [build_classify_prompt(c) for c in cases]
    avg_prompt_tokens = max(1, sum(len(p) // 4 for p in prompts) // len(prompts))
    est_requests = len(cases) * repeats
    est_tokens = est_requests * avg_prompt_tokens
    warning_parts: list[str] = []
    fits = True
    if profile.rpd_limit is not None and est_requests > profile.rpd_limit:
        fits = False
        warning_parts.append(f"запросов {est_requests} > rpd_limit {profile.rpd_limit}")
    if key_tokens_remaining is not None and est_tokens > key_tokens_remaining:
        fits = False
        warning_parts.append(f"оценка токенов {est_tokens} > остаток ключа {key_tokens_remaining}")
    return Forecast(
        est_tokens=est_tokens,
        est_requests=est_requests,
        fits_limits=fits,
        warning="; ".join(warning_parts),
    )


def _mock_profile() -> LLMProfile:
    return LLMProfile(code="mock", provider="mock", model="mock-rules-v1", temperature=0.0)


def _profile_from_code(code: str) -> LLMProfile:
    if code == "mock":
        return _mock_profile()
    return LLMProfile(
        code=code,
        provider="openai_compatible",
        model=code,
        temperature=0.0,
        rpm_limit=18,
        rpd_limit=1000,
    )


async def _invoke_classify(
    chain: ProviderChain,
    case: BenchCase,
    profile: LLMProfile,
    schema: dict[str, Any],
) -> dict[str, Any]:
    prompt = build_classify_prompt(case)
    messages: list[Message] = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": case.text},
    ]
    t0 = time.perf_counter()
    res = await chain.complete_structured(messages, schema, profile, context="default")
    latency_ms = res.usage.latency_ms or int((time.perf_counter() - t0) * 1000)
    predicted = res.obj
    tool_ok = not validate_schema(predicted, schema)
    retries = sum(1 for a in res.attempts if not a.ok)
    json_valid_first_try = bool(res.attempts and res.attempts[0].ok and tool_ok)
    cost_rub = profile.cost(res.usage.prompt_tokens, res.usage.completion_tokens)
    return {
        "case_id": case.case_id,
        "external_id": case.external_id,
        "text": case.text,
        "gold": case.gold,
        "predicted": predicted,
        "correct": compute_correct(case.gold, predicted),
        "latency_ms": latency_ms,
        "json_valid_first_try": json_valid_first_try,
        "retries": retries,
        "prompt_tokens": res.usage.prompt_tokens,
        "completion_tokens": res.usage.completion_tokens,
        "fallback_mock": res.fallback_mock,
        "cost_rub": cost_rub,
        "key_label": res.usage.key_label,
        "tool_ok": tool_ok,
    }


async def run(
    dataset_code: str,
    profile: LLMProfile,
    *,
    repeats: int = 1,
    seed: int | None = 42,
    chain: ProviderChain | None = None,
    key_tokens_remaining: int | None = None,
    cases: list[BenchCase] | None = None,
    record: BenchRunRecord | None = None,
    on_update: Callable[[BenchRunRecord], Awaitable[None]] | None = None,
) -> BenchRunRecord:
    """Запускает прогон; при fits_limits=false не вызывает LLM."""
    global _NEXT_RUN_ID
    repeats = max(1, min(3, repeats))
    cases = load_dataset(dataset_code) if cases is None else cases
    fc = forecast(dataset_code, profile, repeats=repeats, key_tokens_remaining=key_tokens_remaining, cases=cases)
    if record is None:
        record = BenchRunRecord(
            id=_NEXT_RUN_ID,
            dataset_code=dataset_code,
            llm_profile_code=profile.code,
            prompt_version=load_prompt("classify").version,
            seed=seed,
            repeats=repeats,
            status="queued",
        )
        _NEXT_RUN_ID += 1
        _RUNS[record.id] = record
    run_id = record.id

    async def notify() -> None:
        if on_update is not None:
            await on_update(record)

    if not fc.fits_limits:
        record.status = "failed"
        record.error = fc.warning or "лимиты не позволяют прогон"
        record.finished_at = datetime.now(UTC)
        log.warning("bench_forecast_blocked", dataset=dataset_code, warning=fc.warning)
        await notify()
        return record

    schema = deref("agent/classification")
    if chain is None:
        limiter = RateLimiter()
        chain = ProviderChain([MockProvider()], rate_limiter=limiter)

    sem_size = profile.rpm_limit or 8
    sem = asyncio.Semaphore(sem_size)
    record.status = "running"
    record.started_at = datetime.now(UTC)
    await notify()
    total = len(cases) * repeats
    done = 0

    async def one(case: BenchCase, repeat_no: int) -> dict[str, Any]:
        nonlocal done
        async with sem:
            row = await _invoke_classify(chain, case, profile, schema)
        row["run_id"] = run_id
        row["repeat_no"] = repeat_no
        done += 1
        record.progress = done / total if total else 1.0
        return row

    try:
        for repeat_no in range(1, repeats + 1):
            for case in cases:
                if record._cancel:
                    record.status = "cancelled"
                    record.finished_at = datetime.now(UTC)
                    await notify()
                    return record
                record.results.append(await one(case, repeat_no))
                await notify()
        record.metrics = aggregate(record.results, repeats=repeats)
        record.status = "done"
    except asyncio.CancelledError:
        record.status = "cancelled"
        record.finished_at = datetime.now(UTC)
        await notify()
        raise
    except Exception as e:
        record.status = "failed"
        record.error = "benchmark failed: provider or persistence unavailable"
        log.error("bench_run_failed", run_id=run_id, error_type=type(e).__name__)
    record.finished_at = datetime.now(UTC)
    await notify()
    return record


def get_run(run_id: int) -> BenchRunRecord | None:
    return _RUNS.get(run_id)


def list_runs() -> list[BenchRunRecord]:
    return list(_RUNS.values())


def export_run(run_id: int, fmt: Literal["csv", "json"] = "csv") -> str:
    record = _RUNS.get(run_id)
    if record is None:
        raise KeyError(f"прогон {run_id} не найден")
    payload = {
        "run": {
            "id": record.id,
            "dataset_code": record.dataset_code,
            "llm_profile_code": record.llm_profile_code,
            "prompt_version": record.prompt_version,
            "seed": record.seed,
            "repeats": record.repeats,
            "status": record.status,
            "metrics": record.metrics,
            "started_at": record.started_at.isoformat() if record.started_at else None,
            "finished_at": record.finished_at.isoformat() if record.finished_at else None,
        },
        "results": [
            {
                "run_id": r["run_id"],
                "case_id": r["case_id"],
                "repeat_no": r["repeat_no"],
                "text": r["text"],
                "gold": r["gold"],
                "predicted": r["predicted"],
                "correct": r["correct"],
                "latency_ms": r["latency_ms"],
                "json_valid_first_try": r["json_valid_first_try"],
                "retries": r["retries"],
                "prompt_tokens": r["prompt_tokens"],
                "completion_tokens": r["completion_tokens"],
                "fallback_mock": r["fallback_mock"],
            }
            for r in record.results
        ],
    }
    if fmt == "json":
        return json.dumps(payload, ensure_ascii=False, indent=2)
    buf = io.StringIO()
    fields = [
        "run_id",
        "case_id",
        "repeat_no",
        "latency_ms",
        "json_valid_first_try",
        "retries",
        "prompt_tokens",
        "completion_tokens",
        "fallback_mock",
        "correct_signal_type",
        "correct_product",
        "correct_system",
    ]
    writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for r in record.results:
        row = {k: r.get(k) for k in fields if k in r}
        row.update(
            {
                "run_id": r["run_id"],
                "case_id": r["case_id"],
                "repeat_no": r["repeat_no"],
                "correct_signal_type": r["correct"].get("signal_type"),
                "correct_product": r["correct"].get("product"),
                "correct_system": r["correct"].get("system"),
            }
        )
        writer.writerow(row)
    if record.metrics:
        buf.write("\n# metrics\n")
        for k, v in record.metrics.items():
            buf.write(f"{k},{v}\n")
    return buf.getvalue()


class FailOnceProvider:
    """Провайдер для тестов: одна ошибка, далее цепочка переходит на mock."""

    name = "fail_once"

    def __init__(self) -> None:
        self.calls = 0

    async def complete_structured(
        self,
        messages: list[Message],
        schema: dict[str, Any],
        profile: LLMProfile,
        *,
        timeout_s: float,
    ) -> tuple[dict[str, Any], Any, str]:
        self.calls += 1
        raise ProviderError("unavailable", "simulated failure")


async def _cli_main() -> None:
    parser = argparse.ArgumentParser(description="Бенчмарк classify по JSONL")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--profile", default="mock")
    parser.add_argument("--repeats", type=int, default=1)
    args = parser.parse_args()
    profile = _profile_from_code(args.profile)
    if args.profile != "mock":
        fc = forecast(args.dataset, profile, repeats=args.repeats)
        sys.stdout.write(json.dumps(asdict(fc), ensure_ascii=False) + "\n")
        return
    record = await run(args.dataset, profile, repeats=args.repeats)
    sys.stdout.write(
        json.dumps({"status": record.status, "metrics": record.metrics}, ensure_ascii=False, indent=2) + "\n"
    )


def main() -> None:
    asyncio.run(_cli_main())


if __name__ == "__main__":
    main()
