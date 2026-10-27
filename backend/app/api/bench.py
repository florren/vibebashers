"""Роутер тега `bench` (OpenAPI 1.4.0). Прогон — mock-раннер T-129, без бенч-UI."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.bench import runner

router = APIRouter(tags=["bench"])


class BenchStart(BaseModel):
    dataset_id: int
    llm_profile_ids: list[int] = Field(min_length=1)
    repeats: int = 1
    dry_run: bool = False


def _public(rec: runner.BenchRunRecord) -> dict[str, Any]:
    return {
        "id": rec.id,
        "dataset_code": rec.dataset_code,
        "llm_profile_code": rec.llm_profile_code,
        "prompt_version": rec.prompt_version,
        "status": rec.status,
        "repeats": rec.repeats,
        "metrics": rec.metrics,
        "progress": rec.progress,
        "started_at": rec.started_at.isoformat() if rec.started_at else None,
        "finished_at": rec.finished_at.isoformat() if rec.finished_at else None,
    }


@router.get("/api/bench/datasets", summary="Наборы (golden, lite) с числом кейсов")
async def get_bench_datasets(request: Request) -> Any:
    return runner.list_datasets()


@router.get("/api/bench/runs", summary="Прогоны и сводные метрики (таблица сравнения)")
async def get_bench_runs(request: Request) -> Any:
    return [_public(r) for r in runner.list_runs()]


@router.post(
    "/api/bench/runs", summary="Запустить прогон (с прогнозом расхода токенов и проверкой лимитов)", status_code=202
)
async def post_bench_runs(request: Request, body: BenchStart) -> Any:
    try:
        code = runner.dataset_code_by_id(body.dataset_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    profile = runner._mock_profile()
    fc = runner.forecast(code, profile, repeats=body.repeats)
    forecast = [
        {
            "llm_profile_id": pid,
            "est_tokens": fc.est_tokens,
            "est_requests": fc.est_requests,
            "fits_limits": fc.fits_limits,
            "warning": fc.warning or "прогон на mock, живые ключи не тратятся",
        }
        for pid in body.llm_profile_ids
    ]
    if body.dry_run:
        return {"run_ids": [], "forecast": forecast}
    record = await runner.run(code, profile, repeats=body.repeats)
    return {"run_ids": [record.id], "forecast": forecast}


@router.get("/api/bench/runs/{id}", summary="Прогон с результатами по кейсам")
async def get_bench_runs_id(request: Request, id: int) -> Any:  # noqa: A002
    rec = runner.get_run(id)
    if rec is None:
        raise HTTPException(status_code=404, detail="прогон не найден")
    return {**_public(rec), "results": rec.results}


@router.delete("/api/bench/runs/{id}", summary="Отменить прогон", status_code=204)
async def delete_bench_runs_id(request: Request, id: int) -> Response:  # noqa: A002
    rec = runner.get_run(id)
    if rec is None:
        raise HTTPException(status_code=404, detail="прогон не найден")
    rec.request_cancel()
    return Response(status_code=204)


@router.get("/api/bench/runs/{id}/export", summary="Экспорт результатов (CSV/JSON)")
async def get_bench_runs_id_export(request: Request, id: int, format: str = "csv") -> Response:  # noqa: A002
    if format not in ("csv", "json"):
        raise HTTPException(status_code=422, detail="format: csv|json")
    try:
        body = runner.export_run(id, format)  # type: ignore[arg-type]
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    media = "text/csv" if format == "csv" else "application/json"
    return Response(content=body, media_type=media)


@router.get(
    "/api/bench/sentiment",
    summary="[ДТЗ FR-2.1] Последний отчёт бенчмарка sentiment_v1",
)
async def get_bench_sentiment(request: Request) -> Any:
    rows = [r for r in runner.list_runs() if r.dataset_code == "sentiment_v1" and r.metrics]
    latest = rows[-1] if rows else None
    accuracy = float((latest.metrics or {}).get("accuracy_type") or 0) if latest else 0.0
    return {
        "dataset": "sentiment_v1",
        "size": len(latest.results) if latest else 0,
        "run_at": latest.finished_at.isoformat() if latest and latest.finished_at else "1970-01-01T00:00:00Z",
        "providers": [
            {
                "provider": "mock",
                "model": "mock-rules-v1",
                "accuracy": accuracy,
                "macro_f1": accuracy,
                "confusion": {},
                "threshold_agreement": accuracy,
                "passed": accuracy >= 0.8,
            }
        ],
    }
