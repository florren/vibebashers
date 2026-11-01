"""Ошибки API в формате problem+json (RFC 9457) — единственный формат ошибок (contracts/api/openapi.yaml, схема Problem)."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.logging import get_logger

log = get_logger(__name__)
PROBLEM = "application/problem+json"


class Problem(Exception):
    def __init__(
        self, status: int, title: str, detail: str | None = None, type_: str = "about:blank", **extra: Any
    ) -> None:
        super().__init__(detail or title)
        self.status, self.title, self.detail, self.type, self.extra = status, title, detail, type_, extra

    def to_response(self, instance: str | None = None) -> JSONResponse:
        body: dict[str, Any] = {"type": self.type, "title": self.title, "status": self.status}
        if self.detail:
            body["detail"] = self.detail
        if instance:
            body["instance"] = instance
        body.update(self.extra)
        return JSONResponse(body, status_code=self.status, media_type=PROBLEM)


class NotImplementedYet(Problem):
    """501 для эндпоинтов, которые описаны в OpenAPI, но ещё не реализованы (карточка указывается в detail)."""

    def __init__(self, card: str) -> None:
        super().__init__(
            501, "Не реализовано", f"Эндпоинт описан в OpenAPI 1.5.0, реализация — карточка {card}", card=card
        )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(Problem)
    async def _problem(request: Request, exc: Problem) -> JSONResponse:
        return exc.to_response(str(request.url.path))

    @app.exception_handler(HTTPException)
    async def _http(request: Request, exc: HTTPException) -> JSONResponse:
        response = Problem(exc.status_code, str(exc.detail) if exc.detail else "Ошибка").to_response(
            str(request.url.path)
        )
        response.headers.update(exc.headers or {})
        return response

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        return Problem(422, "Невалидный запрос", "Проверьте поля запроса", errors=exc.errors()).to_response(
            str(request.url.path)
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled", path=str(request.url.path))
        return Problem(500, "Внутренняя ошибка").to_response(str(request.url.path))
