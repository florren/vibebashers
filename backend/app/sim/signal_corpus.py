"""T-019: развёртка исходной грамматики в проверяемую матрицу каналов."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class SignalTemplate:
    id: str
    signal_type: str
    product: str
    channel: str
    language: str
    style: str
    text: str
    body: str
    wrapper: str
    gold: dict[str, Any]


class SignalCorpus:
    def __init__(self, path: Path) -> None:
        self.data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
        self.english_share = float(self.data["english_share"])
        self.noise_share = float(self.data["noise_share"])
        if not 0 <= self.english_share <= 1 or not 0 <= self.noise_share <= 1:
            raise ValueError("доли языка и шума должны быть в диапазоне 0..1")
        self.templates: dict[tuple[str, str, str, str], list[SignalTemplate]] = {}
        for kind, spec in self.data["types"].items():
            for product, names in self.data["products"].items():
                for channel, wrappers in self.data["channels"].items():
                    for language in ("ru", "en"):
                        rows = []
                        for index, source in enumerate(spec[language]):
                            body = source["text"] if isinstance(source, dict) else source
                            style = source["style"] if isinstance(source, dict) else "plain"
                            # Подстановка корпуса не заполняет суммы/город: это делает seeded TextGen.
                            body = body.replace("{product}", names[language])
                            wrapper = wrappers[language].replace("{product}", names[language])
                            text = wrapper.replace("{text}", body)
                            template_id = f"{kind}:{product}:{channel}:{language}:{index}"
                            rows.append(
                                SignalTemplate(
                                    template_id,
                                    kind,
                                    product,
                                    channel,
                                    language,
                                    style,
                                    text,
                                    body,
                                    wrapper,
                                    {"sentiment": spec["sentiment"], "negativity": spec["negativity"]},
                                )
                            )
                        self.templates[kind, product, channel, language] = rows

    def for_channel(self, kind: str, product: str, channel: str, language: str) -> list[SignalTemplate]:
        try:
            return self.templates[kind, product, channel, language]
        except KeyError as exc:
            raise ValueError(f"нет шаблонов {kind}/{product}/{channel}/{language}") from exc
