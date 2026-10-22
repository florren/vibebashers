"""Единый детерминированный генератор (T-031 п. 4): random.Random с сериализацией состояния в sim_state.rng_state."""

from __future__ import annotations

import random
from typing import Any


class SimRng(random.Random):
    def dump_state(self) -> dict[str, Any]:
        version, internal, gauss = self.getstate()
        return {"version": version, "internal": list(internal), "gauss": gauss}

    def load_state(self, state: dict[str, Any] | None) -> None:
        if not state:
            return
        self.setstate((state["version"], tuple(state["internal"]), state.get("gauss")))

    def poisson(self, lam: float) -> int:
        """Кнут; при больших λ — нормальная аппроксимация."""
        if lam <= 0:
            return 0
        if lam > 50:
            return max(0, round(self.gauss(lam, lam**0.5)))
        import math

        limit, k, p = math.exp(-lam), 0, 1.0
        while True:
            p *= self.random()
            if p < limit:
                return k
            k += 1

    def weighted(self, items: dict[str, float]) -> str:
        total = sum(items.values())
        r = self.random() * total
        acc = 0.0
        for k, v in items.items():
            acc += v
            if r < acc:
                return k
        return next(iter(items))
