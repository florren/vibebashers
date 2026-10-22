"""structlog: JSON в prod, читаемый вывод в dev. print запрещён (AGENTS.md §8)."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import structlog


def configure_logging(env: str = "dev", jsonl_path: Path | None = None, jsonl_level: str = "info") -> None:
    """Консоль (dev — читаемо, prod — JSON) плюс JSONL-файл для разбора людьми и агентами (docs/REPORTS.md)."""
    processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
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
