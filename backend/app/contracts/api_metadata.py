"""Метаданные протокола берутся из того же контракта, что и клиентские типы."""

from functools import lru_cache
from pathlib import Path

import yaml

from app.contracts.registry import ROOT


@lru_cache
def api_version(path: Path = ROOT / "contracts/api/openapi.yaml") -> str:
    """Контракт неизменен в рамках процесса; отсутствие версии не маскируется."""
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    info = document.get("info") if isinstance(document, dict) else None
    version = info.get("version") if isinstance(info, dict) else None
    if not isinstance(version, str) or not version.strip():
        raise ValueError("Канонический OpenAPI должен содержать непустой info.version")
    return version
