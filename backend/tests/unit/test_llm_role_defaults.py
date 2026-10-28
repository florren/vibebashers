"""Назначение моделей ролям соответствует решению заказчика и ТЗ 5.2."""

from pathlib import Path

import yaml

from app.config import Settings
from app.llm.failover import default_profile

ROOT = Path(__file__).resolve().parents[3]


def test_seed_model_roles() -> None:
    rows = yaml.safe_load((ROOT / "data/llm_profiles.yaml").read_text())["llm_profiles"]
    profiles = {row["code"]: row for row in rows}
    for code, role, model in (
        ("gigachat_ultra", "main", "GigaChat-3-Ultra"),
        ("gigachat_pro", "twin", "GigaChat-3-Pro"),
        ("gigachat_lightning", "fast", "GigaChat-3-Lightning"),
    ):
        assert profiles[code]["role"] == role
        assert profiles[code]["model"] == model
        assert profiles[code]["is_active"] is True


def test_agent_default_matches_seed_main(monkeypatch) -> None:
    monkeypatch.delenv("GIGACHAT_MODEL", raising=False)
    settings = Settings(_env_file=None, llm_provider="gigachat")
    profile = default_profile(settings)
    assert profile.role == "main"
    assert profile.model == "GigaChat-3-Ultra"
    assert "GIGACHAT_MODEL=GigaChat-3-Ultra" in (ROOT / ".env.example").read_text()
