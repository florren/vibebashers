"""T-019: корпусные критерии измеряются на реальных текстах и неизменённом Mock."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from string import Formatter

import pytest
import yaml

from app.llm.mock import analyze
from app.sim.signal_corpus import SignalCorpus
from app.sim.textgen import DATA, TextGen


def test_corpus_has_only_generic_bank_references_and_no_contacts() -> None:
    gen = TextGen(31)
    texts = [row.text for group in gen.corpus.templates.values() for row in group]
    texts.extend(text for group in gen.corpus.data["noise"].values() for text in group)
    bank_words = {
        "банк",
        "банка",
        "банку",
        "банком",
        "банке",
        "банковских",
        "банковское",
        "bank",
        "banking",
        "non-banking",
    }
    for text in texts:
        assert not re.search(r"https?://|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", text)
        assert not re.search(r"(?<!\w)\+?\d[\d ()-]{9,}\d(?!\w)", text)
        assert not re.search(r"(?<!\d)\d{12,19}(?!\d)", text)
        # Названия банков с bank/банк и аббревиатуры заменены нейтральным «Банк».
        assert set(re.findall(r"\b[\w-]*(?:банк|bank)[\w-]*\b", text.casefold())) <= bank_words
        assert set(re.findall(r"\b[A-ZА-ЯЁ]{2,}\b", text)) <= {"RUB"}


def test_entire_corpus_covers_actual_reference_matrix_without_duplicate_texts() -> None:
    gen = TextGen(17)
    types = {r["code"] for r in yaml.safe_load((DATA / "error_codes.yaml").read_text())["signal_types"]}
    products = {r["code"] for r in yaml.safe_load((DATA / "products.yaml").read_text())["products"]}
    channels = {r["code"] for r in yaml.safe_load((DATA / "channels.yaml").read_text())["channels"]}
    expected = {(t, p, c, lang) for t in types for p in products for c in channels for lang in ("ru", "en")}
    assert set(gen.corpus.templates) == expected
    rows = [r for group in gen.corpus.templates.values() for r in group]
    source_texts = [
        row["text"] if isinstance(row, dict) else row
        for spec in gen.corpus.data["types"].values()
        for language in ("ru", "en")
        for row in spec[language]
    ] + [value for wrapper in gen.corpus.data["channels"].values() for value in wrapper.values()]
    fields = {field for text in source_texts for _, field, _, _ in Formatter().parse(text) if field}
    assert {"amount", "days", "product", "promo_rate", "rate", "city"} <= fields
    assert len({r.id for r in rows}) == len({r.text for r in rows}) == len(rows) >= 400
    for (t, p, c, language), group in gen.corpus.templates.items():
        assert len(group) >= (3 if language == "ru" else 1)
        assert all((r.signal_type, r.product, r.channel, r.language) == (t, p, c, language) for r in group)
        for row in group:
            text = gen._fill(row.text, p, "Москва", "4512")
            assert "{" not in text and "}" not in text
            assert "4512451245124512" not in text
            assert row.gold["sentiment"] in ("positive", "neutral", "negative")
    assert sum(r.style != "plain" for r in rows if r.language == "ru") / sum(r.language == "ru" for r in rows) >= 0.25


def test_hard_corpus_accuracy_is_measured_with_existing_mock_without_gold_input() -> None:
    gen = TextGen(23)
    rows = [r for group in gen.corpus.templates.values() for r in group if r.language == "ru" and r.style != "plain"]
    hits = sum(analyze(gen._fill(r.text, r.product, "Самара", "4512"))["signal_type"] == r.signal_type for r in rows)
    assert len(rows) >= 100
    assert hits / len(rows) <= 0.75


def test_language_style_noise_and_rendering_are_seeded_and_have_truthful_hints() -> None:
    a, b = TextGen(713), TextGen(713)
    counts: Counter[str] = Counter()
    for i in range(5000):
        t = list(a.corpus.data["types"])[i % 10]
        p = list(a.corpus.data["products"])[i % 4]
        c = list(a.corpus.data["channels"])[i % 12]
        left, right = a.generate(t, p, channel=c), b.generate(t, p, channel=c)
        assert left == right
        assert left.gold["signal_type"] == t and left.gold["product"] == p
        assert left.gold["channel"] == c
        assert left.gold["language"] in ("ru", "en")
        counts[left.gold["language"]] += 1
        counts["hard"] += left.style != "plain"
    assert 0.035 <= counts["en"] / 5000 <= 0.065
    assert counts["hard"] / 5000 >= 0.25
    for _ in range(20):
        left, right = a.noise(), b.noise()
        assert left == right
        assert left.gold["noise"] is True
        assert not left.signal_type and not left.product
        assert "signal_type" not in left.gold and "product" not in left.gold


@pytest.mark.parametrize(
    "channel,marker", [("call", "00:00 Оператор:"), ("chat", "Клиент:"), ("email", "Тема:"), ("social", "#Банк")]
)
@pytest.mark.parametrize("style", ["plain", "sarcasm", "slang", "typos", "caps"])
def test_channel_format_is_present(channel: str, marker: str, style: str) -> None:
    gen = TextGen(0)
    item = gen.generate("tech_fault", "deposit", channel=channel, language="ru", style=style)
    assert marker in item.text
    assert ("\n" in item.text) == (channel in ("call", "chat", "email"))


def test_invalid_selection_fails_explicitly_and_corpus_rejects_invalid_shares(tmp_path: Path) -> None:
    gen = TextGen(0)
    with pytest.raises(ValueError, match="нет шаблонов"):
        gen.generate("tech_fault", "deposit", channel="not-a-channel")
    with pytest.raises(ValueError, match="нет шаблонов"):
        gen.generate("tech_fault", "deposit", channel="chat", language="fr")
    with pytest.raises(ValueError, match="нужен channel"):
        gen.generate("tech_fault", "deposit", language="en")
    with pytest.raises(ValueError, match="язык"):
        gen.noise(language="fr")
    path = tmp_path / "invalid.yaml"
    path.write_text("english_share: -0.01\nnoise_share: 0.03\n")
    with pytest.raises(ValueError, match="доли"):
        SignalCorpus(path)


def test_channel_corpus_continues_from_persisted_world_rng() -> None:
    from unittest.mock import Mock

    from app.sim.generators import World
    from app.sim.rng import SimRng

    rng = SimRng(1729)
    original = World(Mock(), Mock(), rng, 1)

    def sample(world: World) -> list[tuple[object, float, int]]:
        return [
            (
                world.textgen.generate(kind, product, channel=channel, psychotype="public_emotional"),
                world.rng.random(),
                world.rng.poisson(4),
            )
            for kind, product in world.textgen.all_combinations()
            for channel in ("chat", "call", "email", "social")
        ]

    sample(original)
    checkpoint = rng.dump_state()
    expected = sample(original)
    expected_end = rng.dump_state()
    restored_rng = SimRng(0)
    restored_rng.load_state(checkpoint)
    restored = World(Mock(), Mock(), restored_rng, 1)
    assert sample(restored) == expected
    assert restored_rng.dump_state() == expected_end
