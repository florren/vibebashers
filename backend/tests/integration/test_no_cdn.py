"""T-263: собранный frontend содержит все локальные шрифты без CDN."""

from __future__ import annotations

import re
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
    for path in built_dist.rglob("*"):
        if path.is_file() and path.suffix in {".html", ".css", ".js", ".map"}:
            text = path.read_text(encoding="utf-8", errors="ignore")
            for needle in FORBIDDEN:
                assert needle not in text, f"найден внешний URL: {needle}"


def test_dist_references_local_fonts(built_dist: Path) -> None:
    css = "\n".join(p.read_text(encoding="utf-8") for p in built_dist.rglob("*.css"))
    expected = {
        f"{family}-{alphabet}-{weight}.woff2"
        for family, weights in (("inter", (400, 500, 600, 700)), ("jetbrains-mono", (400, 500)))
        for alphabet in ("latin", "cyrillic")
        for weight in weights
    }
    faces = re.findall(r"@font-face\s*\{([^}]+)\}", css)
    assert len(faces) == 12
    references = set()
    for face in faces:
        assert re.search(r"font-display\s*:\s*swap", face)
        urls = re.findall(r"url\([\"']?([^\)\"']+)", face)
        assert len(urls) == 1
        assert urls[0].startswith("/fonts/"), f"внешний шрифт: {urls[0]}"
        references.add(urls[0].removeprefix("/fonts/"))
    assert references == expected
    for name in expected:
        blob = (built_dist / "fonts" / name).read_bytes()
        assert blob[:4] == b"wOF2" and len(blob) > 1000, name
    for license_name in ("Inter-OFL.txt", "JetBrainsMono-OFL.txt"):
        notice = (built_dist / "fonts" / license_name).read_text()
        assert "Copyright" in notice and "SIL OPEN FONT LICENSE Version 1.1" in notice
