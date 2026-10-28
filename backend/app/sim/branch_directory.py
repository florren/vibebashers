"""Локальный справочник ВСП: детерминированная синтетика или ручной snapshot, без сети."""

from __future__ import annotations

import csv
import datetime as dt
import json
import random
from pathlib import Path
from typing import Any, Protocol

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "data" if (ROOT / "data").exists() else Path("/data")


class Branch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=3, max_length=32)
    name_ru: str
    city_id: int
    region_code: str
    desks: int = Field(default=6, ge=1, le=6)
    manager_display_name: str = "Учебный руководитель"
    branch_type: str = Field(pattern="^(flagship|standard|additional|mobile)$")
    branch_status: str = Field(pattern="^(open|closed)$")
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    address_ru: str
    hours_ru: str
    opened_sim: dt.datetime
    closed_sim: dt.datetime | None = None
    product_line_codes: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def dates(self) -> Branch:
        if self.opened_sim.tzinfo is None or (self.closed_sim and self.closed_sim.tzinfo is None):
            raise ValueError("даты должны включать часовой пояс")
        if (self.branch_status == "closed") != (self.closed_sim is not None):
            raise ValueError("статус closed требует closed_sim; open запрещает closed_sim")
        if self.closed_sim and self.closed_sim < self.opened_sim:
            raise ValueError("закрытие раньше открытия")
        return self


class BranchDirectoryProvider(Protocol):
    def load(self, seed: int, sim_time: dt.datetime) -> list[Branch]: ...


def _catalogs() -> tuple[list[dict[str, str]], list[dict[str, str]], list[str]]:
    with (DATA / "regions.csv").open() as stream:
        regions = list(csv.DictReader(stream))
    with (DATA / "cities.csv").open() as stream:
        cities = list(csv.DictReader(stream))
    lines = yaml.safe_load((DATA / "product_lines.yaml").read_text())["product_lines"]
    return regions, cities, [line["code"] for line in lines]


class SyntheticBranchDirectory:
    def load(self, seed: int, sim_time: dt.datetime) -> list[Branch]:
        regions, cities, lines = _catalogs()
        legacy = yaml.safe_load((DATA / "branches.yaml").read_text())["branches"]
        rng = random.Random(seed)
        closed_codes = set(rng.sample(range(10, 240), 19))
        branches = []
        for i in range(240):
            old = legacy[i] if i < len(legacy) else None
            if old:
                city = max((c for c in cities if c["name_ru"] == old["city"]), key=lambda c: int(c["population"]))
            else:
                region = regions[(i - len(legacy)) % len(regions)]
                available = [c for c in cities if c["region_code"] == region["code"]]
                city = available[rng.randrange(len(available))]
            opened = sim_time - dt.timedelta(days=720 if old else rng.randint(20, 500))
            closed = (
                max(opened + dt.timedelta(days=1), sim_time - dt.timedelta(days=rng.randint(1, 90)))
                if i in closed_codes
                else None
            )
            branches.append(
                Branch(
                    code=old["code"] if old else f"S{i:04d}",
                    name_ru=old["name_ru"] if old else f"Учебное ВСП {i:04d}",
                    city_id=int(city["id"]),
                    region_code=city["region_code"],
                    desks=old["desks"] if old else 6,
                    manager_display_name=old["manager_display_name"] if old else f"Учебный руководитель {i:04d}",
                    branch_type="flagship" if i < 3 else ("standard", "additional", "mobile")[i % 3],
                    branch_status="closed" if closed else "open",
                    lat=round(float(city["lat"]) + rng.uniform(-0.015, 0.015), 6),
                    lon=round(float(city["lon"]) + rng.uniform(-0.025, 0.025), 6),
                    address_ru=f"Учебная улица, дом {i + 1} (синтетический адрес)",
                    hours_ru="Пн–Пт 09:00–18:00",
                    opened_sim=opened,
                    closed_sim=closed,
                    product_line_codes=sorted(rng.sample(lines, rng.randint(1, 4))),
                )
            )
        return branches


class SnapshotBranchDirectory:
    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        if not self.path.is_relative_to((DATA / "import" / "branches").resolve()):
            raise ValueError("snapshot должен лежать в data/import/branches")

    def load(self, seed: int, sim_time: dt.datetime) -> list[Branch]:
        if self.path.suffix.lower() == ".json":
            doc = json.loads(self.path.read_text())
            rows = doc["branches"] if isinstance(doc, dict) else doc
        elif self.path.suffix.lower() == ".csv":
            with self.path.open(newline="") as stream:
                rows = list(csv.DictReader(stream))
            for row in rows:
                row["product_line_codes"] = json.loads(row["product_line_codes"])
                if not row.get("closed_sim"):
                    row["closed_sim"] = None
        else:
            raise ValueError("snapshot: ожидается CSV или JSON")
        if not isinstance(rows, list):
            raise ValueError("snapshot: ожидается массив branches")
        regions, cities, lines = _catalogs()
        city_regions = {int(c["id"]): c["region_code"] for c in cities}
        known_regions = {r["code"] for r in regions}
        # Исходные отделения сценариев сохраняются и на чистой БД со snapshot.
        merged = {b.code: b for b in SyntheticBranchDirectory().load(seed, sim_time)[:10]}
        seen = set()
        for i, row in enumerate(rows, start=1):
            try:
                branch = Branch.model_validate(row)
                if branch.code in seen:
                    raise ValueError("повтор кода ВСП")
                if branch.region_code not in known_regions or city_regions.get(branch.city_id) != branch.region_code:
                    raise ValueError("город и регион не согласованы")
                if not set(branch.product_line_codes) <= set(lines):
                    raise ValueError("неизвестное продуктовое направление")
                if branch.code in merged:
                    raise ValueError("snapshot не может заменить исходное отделение сценариев")
                seen.add(branch.code)
                merged[branch.code] = branch
            except (ValueError, TypeError) as exc:
                raise ValueError(f"snapshot строка {i}: {exc}") from exc
        return list(merged.values())


def provider(mode: str, path: Path | None = None) -> BranchDirectoryProvider:
    if mode == "synthetic":
        return SyntheticBranchDirectory()
    if mode == "snapshot_file" and path is not None:
        return SnapshotBranchDirectory(path)
    raise ValueError("нужен provider synthetic либо snapshot_file с путём")


def network_history(branches: list[Branch], sim_time: dt.datetime) -> list[dict[str, Any]]:
    rows = []
    current = sim_time.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    months = [current]
    for _ in range(11):
        months.append((months[-1] - dt.timedelta(days=1)).replace(day=1))
    for month in reversed(months):
        following = (month + dt.timedelta(days=32)).replace(day=1)
        for region in sorted({b.region_code for b in branches}):
            group = [b for b in branches if b.region_code == region]
            rows.append(
                {
                    "month": month.date(),
                    "region_code": region,
                    "open_count": sum(
                        b.opened_sim < following and (b.closed_sim is None or b.closed_sim >= following) for b in group
                    ),
                    "closed_count": sum(b.closed_sim is not None and b.closed_sim < following for b in group),
                    "opened_in_month": sum(month <= b.opened_sim < following for b in group),
                    "closed_in_month": sum(
                        b.closed_sim is not None and month <= b.closed_sim < following for b in group
                    ),
                }
            )
    return rows
