"""HTTP-наблюдаемость: request_id, длительность, статус → structlog; счётчики по маршрутам; кольцевой буфер ошибок.

Что считаем «сломалось»: 5xx и исключения. «Работает, но не так»: 4xx (кроме 404 статики), 501 — запрошена
нереализованная функция (сигнал приоритета доработки), медленные запросы (> SLOW_MS).
"""

from __future__ import annotations

import time
import uuid
from collections import Counter, deque
from typing import Any

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.logging import get_logger
from app.observability.redaction import redact_text

log = get_logger("http")

SLOW_MS = 2000
ERRORS_KEEP = 500


def safe_public_path(path: str) -> str:
    """Токен трекинга — секрет доступа, не часть диагностического журнала."""
    for prefix in ("/api/public/track/", "/track/"):
        if path.startswith(prefix):
            return prefix + "{token}"
    return path


class HttpStats:
    def __init__(self) -> None:
        self.started_at = time.time()
        self.by_route_status: Counter[tuple[str, str, int]] = Counter()
        self.latency_sum_ms: Counter[tuple[str, str]] = Counter()
        self.latency_max_ms: dict[tuple[str, str], int] = {}
        self.slow: Counter[tuple[str, str]] = Counter()
        self.errors: deque[dict[str, Any]] = deque(maxlen=ERRORS_KEEP)

    def record(
        self, method: str, route: str, status: int, ms: int, *, path: str, request_id: str, error: str | None
    ) -> None:
        route, path = safe_public_path(route), safe_public_path(path)
        key = (method, route)
        self.by_route_status[(method, route, status)] += 1
        self.latency_sum_ms[key] += ms
        self.latency_max_ms[key] = max(self.latency_max_ms.get(key, 0), ms)
        if ms > SLOW_MS:
            self.slow[key] += 1
        if status >= 400 and not (status == 404 and not path.startswith("/api/")):
            self.errors.append(
                {
                    "ts": time.time(),
                    "request_id": request_id,
                    "method": method,
                    "route": route,
                    "path": path,
                    "status": status,
                    "latency_ms": ms,
                    "error": redact_text(error) if error is not None else None,
                }
            )

    def snapshot(self) -> dict[str, Any]:
        routes: dict[tuple[str, str], dict[str, Any]] = {}
        for (m, r, st), n in self.by_route_status.items():
            slot = routes.setdefault(
                (m, r), {"method": m, "route": r, "total": 0, "s2xx": 0, "s4xx": 0, "s5xx": 0, "s501": 0, "s422": 0}
            )
            slot["total"] += n
            if st == 501:
                slot["s501"] += n
            if st == 422:
                slot["s422"] += n
            if st >= 500 and st != 501:
                slot["s5xx"] += n
            elif 400 <= st < 500:
                slot["s4xx"] += n
            elif st < 400:
                slot["s2xx"] += n
        for key, slot in routes.items():
            slot["avg_ms"] = round(self.latency_sum_ms[key] / max(slot["total"], 1))
            slot["max_ms"] = self.latency_max_ms.get(key, 0)
            slot["slow"] = self.slow.get(key, 0)
        items = sorted(routes.values(), key=lambda x: (-(x["s5xx"] * 100 + x["s501"] * 10 + x["s4xx"]), -x["total"]))
        total = sum(self.by_route_status.values())
        return {
            "since": self.started_at,
            "requests": total,
            "s5xx": sum(n for (_, _, st), n in self.by_route_status.items() if st >= 500 and st != 501),
            "s501": sum(n for (_, _, st), n in self.by_route_status.items() if st == 501),
            "s4xx": sum(n for (_, _, st), n in self.by_route_status.items() if 400 <= st < 500),
            "slow": sum(self.slow.values()),
            "routes": items[:60],
            "recent_errors": list(self.errors)[-50:][::-1],
        }


stats = HttpStats()


class RequestLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path.startswith(("/assets", "/ws")):
            return await call_next(request)
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        structlog.contextvars.bind_contextvars(request_id=rid)
        t0 = time.perf_counter()
        status = 500
        error: str | None = None
        path = safe_public_path(request.url.path)
        try:
            response = await call_next(request)
            if path != request.url.path or request.url.path == "/api/public/claim":
                response.headers["Cache-Control"] = "no-store"
                response.headers["Referrer-Policy"] = "no-referrer"
                response.headers["X-Robots-Tag"] = "noindex, nofollow"
            status = response.status_code
            return response
        except Exception as exc:
            error = type(exc).__name__ if path != request.url.path else f"{type(exc).__name__}: {str(exc)[:200]}"
            raise
        finally:
            ms = int((time.perf_counter() - t0) * 1000)
            route = _route_template(request)
            stats.record(request.method, route, status, ms, path=path, request_id=rid, error=error)
            if (status >= 500 and status != 501) or error:
                log.error(
                    "http_request",
                    method=request.method,
                    route=route,
                    path=path,
                    status=status,
                    latency_ms=ms,
                    error=error,
                )
            elif (
                status == 501
                or status >= 400
                and not (status == 404 and not request.url.path.startswith("/api/"))
                or ms > SLOW_MS
            ):
                log.warning(
                    "http_request",
                    method=request.method,
                    route=route,
                    path=path,
                    status=status,
                    latency_ms=ms,
                    slow=ms > SLOW_MS,
                )
            else:
                log.debug("http_request", method=request.method, route=route, status=status, latency_ms=ms)
            structlog.contextvars.unbind_contextvars("request_id")


def _route_template(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return str(path) if path else request.url.path
