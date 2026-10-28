"""TLS GigaChat: системные CA и публичная цепочка НУЦ Минцифры."""

from __future__ import annotations

import ssl
from pathlib import Path

import certifi

BUNDLED_CA = Path(__file__).resolve().parent / "certs" / "gigachat-ca.pem"


def context(bundle: str | None = None) -> ssl.SSLContext:
    ctx = ssl.create_default_context(cafile=certifi.where())
    ctx.load_verify_locations(cafile=bundle or str(BUNDLED_CA))
    return ctx
