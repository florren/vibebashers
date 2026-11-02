"""structlog: JSON в prod, читаемый вывод в dev. print запрещён (AGENTS.md §8)."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import structlog

from app.observability.redaction import redact_event, redact_tracking_urls


class PublicTokenFilter(logging.Filter):
    """Uvicorn пишет access log вне HTTP middleware: скрываем секретные ссылки и здесь."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple) and len(record.args) == 5:
            args = list(record.args)
            args[2] = redact_tracking_urls(str(args[2]))
            record.args = tuple(args)
        return True


def configure_logging(env: str = "dev", jsonl_path: Path | None = None, jsonl_level: str = "info") -> None:
    """Консоль (dev — читаемо, prod — JSON) плюс JSONL-файл для разбора людьми и агентами (docs/REPORTS.md)."""
    access_logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, PublicTokenFilter) for item in access_logger.filters):
        access_logger.addFilter(PublicTokenFilter())
    processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        redact_event,
    ]
    if jsonl_path is not None:
        from app.observability.jsonl import JsonlSink

        processors.append(JsonlSink(jsonl_path, min_level=jsonl_level))
    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer(ensure_ascii=False) if env == "prod" else structlog.dev.ConsoleRenderer()
    )
    structlog.configure(
        processors=[*processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO if env != "dev" else logging.DEBUG),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)  # type: ignore[no-any-return]
