"""T-197: install.sh --record-cassettes выставляет LLM_RECORD до compose up."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
INSTALL_SH = ROOT / "install.sh"


def test_install_help_lists_record_cassettes() -> None:
    r = subprocess.run(
        [str(INSTALL_SH), "--help"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0
    assert "--record-cassettes" in r.stdout


def test_install_sh_parses_record_cassettes_and_sets_llm_record() -> None:
    text = INSTALL_SH.read_text(encoding="utf-8")
    assert "--record-cassettes" in text
    assert "RECORD_CASSETTES" in text
    assert "LLM_RECORD=1" in text
    assert 's|^LLM_RECORD=.*|LLM_RECORD=1|' in text
