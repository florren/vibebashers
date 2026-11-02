"""T-240/T-247: синтетические reviews и CSI без ПДн/реальных source URLs."""

import json
import re
from pathlib import Path

from app.corpus.reviews import parse_reviews, platforms
from app.sim.csi_corpus import generate

ROOT = Path(__file__).resolve().parents[3]
CORPUS = ROOT / "data/corpus/reviews/product_lines_v1/reviews.json"


def test_no_pii_and_no_real_bank_names_or_urls() -> None:
    rows = parse_reviews(CORPUS)
    for row in rows:
        assert not re.search(r"\b(?:\d[ -]?){10,16}\b|[\w.+-]+@[\w.-]+\.[a-z]{2,}", row.text, re.I)
        assert not re.search(r"Сбербанк|Тинькофф|Альфа.Банк|ВТБ|Райффайзен|Газпромбанк|https?://", row.text, re.I)
        assert ".invalid/" in row.source_url
    for platform in platforms().values():
        assert not re.search(r"https?://|www\.", platform.name_ru + platform.name_en)


def test_no_pii_in_synthetic_csi_corpus():
    corpus = generate()
    forbidden = {"display_name", "name", "phone", "email", "chat_id", "account", "card_number", "address"}
    for row in corpus["complaints"] + corpus["employees"]:
        assert not forbidden.intersection(row)
    for row in corpus["complaints"]:
        text = row["complaint_ru"]
        assert text.startswith("Учебная жалоба:")
        assert not re.search(r"https?://|www\.|[\w.+-]+@[\w.-]+|\+?\d[\d ()-]{8,}\d", text)
    assert "Authorization" not in json.dumps(corpus)
