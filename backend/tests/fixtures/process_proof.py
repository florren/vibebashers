"""Атомарная публикация JSON-маркеров между тестовыми процессами."""

import json
import uuid
from pathlib import Path
from typing import Any


def publish_json(path: Path, value: dict[str, Any]) -> None:
    # exists() у читателя означает, что запись уже завершена и файл закрыт.
    temporary = path.with_name(f".{path.name}-{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(value), encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
