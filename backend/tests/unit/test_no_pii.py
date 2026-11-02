"""Структурная и текстовая проверка локального synthetic CSI corpus, не общий PII detector."""

import json
import re

from app.sim.csi_corpus import generate


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
