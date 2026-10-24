"""Узлы гraphа агента (T-056…T-174): загрузка из gzip+base64."""
from __future__ import annotations
import base64 as _b64
import gzip as _gzip
from pathlib import Path as _Path

_base = _Path(__file__)
_parts = sorted(_base.parent.glob("nodes.gz.b64.c*"))
_payload = "".join(p.read_text(encoding="ascii") for p in _parts)
exec(compile(_gzip.decompress(_b64.b64decode(_payload)).decode("utf-8"), str(_base), "exec"), globals(), globals())
