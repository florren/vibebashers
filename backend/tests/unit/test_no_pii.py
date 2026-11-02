"""T-240: только синтетические отзывы/названия и reserved source URLs."""

import re
from pathlib import Path

from app.corpus.reviews import parse_reviews, platforms

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
