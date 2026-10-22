"""Генерация текстов сигналов из data/corpus/signal_templates.yaml с вариативностью (T-016, B03): тон, сарказм, сленг, опечатки, капс.

Детерминирована seed'ом. Возвращает текст и gold-разметку (для bench и матрицы покрытия)."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "data"


def load_yaml(rel: str) -> Any:
    return yaml.safe_load((DATA / rel).read_text(encoding="utf-8"))


STYLE_SHARE = {
    "plain": 0.60,
    "sarcasm": 0.14,
    "slang": 0.10,
    "typos": 0.10,
    "caps": 0.06,
}  # ≥ 25 % «трудных» для правил


@dataclass
class Generated:
    text: str
    signal_type: str
    product: str
    style: str
    gold: dict[str, Any] = field(default_factory=dict)


class TextGen:
    def __init__(self, seed: int) -> None:
        self.rnd = random.Random(seed)
        self.c = load_yaml("corpus/signal_templates.yaml")
        self.templates: dict[str, dict[str, list[dict[str, Any]]]] = self.c["templates"]

    def _fill(self, text: str, product: str, city: str, card4: str) -> str:
        r = self.rnd
        return text.format(
            amount=f"{r.choice(self.c['amounts'][product]):,}".replace(",", " "),
            fee=r.choice(self.c["fees"]),
            card4=f"**** {card4}",
            city=city,
            days=r.choice([2, 3, 4]),
            product=product,
            branch=r.choice(self.c["branches"]),
            rate="9,5",
            promo_rate="14",
            month=r.choice(self.c["months"]),
            op="оплата",
        )

    def _style(self, text: str, style: str) -> str:
        r = self.rnd
        if style == "sarcasm":
            w = str(r.choice(self.c["sarcasm_wrappers"]))
            core = text.rstrip(".!? ")
            lower = core[0].lower() + core[1:] if core else core
            return w.format(text=core + ".", lower=lower + ".")
        if style == "slang":
            for a, b in r.sample(self.c["slang"], k=min(3, len(self.c["slang"]))):
                text = text.replace(a, b)
            return text.rstrip(".!?") + r.choice(["", " ((", "...", " жесть", " капец"])
        if style == "typos":
            for a, b in r.sample(self.c["typos"], k=min(4, len(self.c["typos"]))):
                text = text.replace(a, b).replace(a.capitalize(), b.capitalize())
            return text.replace(", ", " ").lower() if r.random() < 0.5 else text
        if style == "caps":
            words = text.split(" ")
            i = r.randrange(len(words))
            words[i] = words[i].upper()
            return " ".join(words).rstrip(".") + "!!!"
        return text

    def pick_style(self, psychotype: str) -> str:
        r = self.rnd.random()
        bias = {"public_emotional": {"sarcasm": 0.15}, "youth": {"slang": 0.15}, "novice": {"typos": 0.1}}.get(
            psychotype, {}
        )
        shares = {**STYLE_SHARE}
        for k, v in bias.items():
            shares[k] += v
            shares["plain"] -= v
        acc = 0.0
        for k, v in shares.items():
            acc += v
            if r < acc:
                return k
        return "plain"

    def generate(
        self,
        signal_type: str,
        product: str,
        *,
        psychotype: str = "loyal_pragmatic",
        city: str = "Москва",
        card4: str = "4512",
        style: str | None = None,
    ) -> Generated:
        tpl = self.rnd.choice(self.templates[signal_type][product])
        style = style or self.pick_style(psychotype)
        if (
            signal_type in ("gratitude", "info_request", "suggestion", "legal_regulatory", "fraud_suspicion")
            and style == "sarcasm"
        ):
            style = "plain"  # сарказм поверх благодарности ломает gold
        text = self._style(self._fill(tpl["text"], product, city, card4), style)
        gold = {**tpl.get("gold", {}), "signal_type": signal_type, "product": product, "style": style}
        if style == "sarcasm":
            gold["sentiment"] = "negative"
            gold["hidden_negativity"] = True
            gold["flags"] = sorted({*gold.get("flags", []), "sarcasm"})
            gold["negativity"] = max(int(gold.get("negativity", 50)), 60)
        return Generated(text, signal_type, product, style, gold)

    def all_combinations(self) -> list[tuple[str, str]]:
        return [(st, p) for st, by_p in self.templates.items() for p in by_p]
