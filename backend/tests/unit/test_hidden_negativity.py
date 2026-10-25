"""T-211: цитата скрытого негатива обязана быть подстрокой текста."""

from app.agent.nodes import clamp_hidden_evidence
from app.agent.prompts import load


def test_evidence_must_be_substring() -> None:
    text = "Спасибо, что списали комиссию, очень удобно"
    hidden = clamp_hidden_evidence(
        text,
        {"sarcasm": {"present": True, "confidence": 0.9, "evidence_ru": "не из текста"}},
    )
    assert hidden["sarcasm"]["evidence_ru"] is None
    assert hidden["sarcasm"]["confidence"] == 0.63


def test_evidence_kept_when_quoted() -> None:
    text = "Очень приятно видеть комиссию"
    hidden = clamp_hidden_evidence(
        text,
        {"sarcasm": {"present": True, "confidence": 1.0, "evidence_ru": "Очень приятно"}},
    )
    assert hidden["sarcasm"]["evidence_ru"] == "Очень приятно"


def test_normalize_prompt_has_few_shot() -> None:
    body = load("normalize").body
    assert "Очень приятно" in body
    assert "отдельный вызов модели не делай" in body
