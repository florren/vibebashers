"""T-263: собранный frontend/dist не ссылается на внешние шрифты и CDN."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
DIST = ROOT / "frontend" / "dist"

FORBIDDEN = ("fonts.googleapis.com", "fonts.gstatic.com", "use.typekit.net")

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def built_dist() -> Path:
    if not DIST.is_dir():
        pytest.skip("frontend/dist отсутствует — выполните cd frontend && npm run build")
    return DIST


def test_dist_has_no_external_font_cdns(built_dist: Path) -> None:
    blobs: list[str] = []
    for path in built_dist.rglob("*"):
        if path.is_file() and path.suffix in {".html", ".css", ".js", ".map"}:
            blobs.append(path.read_text(encoding="utf-8", errors="ignore"))
    joined = "\n".join(blobs)
    for needle in FORBIDDEN:
        assert needle not in joined, f"найден внешний URL: {needle}"


def test_dist_references_local_fonts(built_dist: Path) -> None:
    woff2 = list(built_dist.rglob("*.woff2"))
    css = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in built_dist.rglob("*.css"))
    assert woff2 or "/fonts/" in css, "ожидались локальные woff2 или url(/fonts/) в CSS"
