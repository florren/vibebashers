"""T-248: явно заданная синтетическая когорта с направлением и прошлым окном.

Не реконструирует legacy visits и не калибрует реальные вероятности. Стандартный
csi_v1 остаётся неизменным; другой CSI namespace не подменяет прежние записи.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import yaml

from app.sim.branch_directory import SyntheticBranchDirectory
from app.sim.csi_corpus import DATA, generate


def generate_scoped(seed: int | None = None, *, id_base: int = 30000) -> dict[str, Any]:
    if isinstance(id_base, bool) or not 30000 <= id_base <= 899400 or id_base % 300:
        raise ValueError("CSI id_base: кратное300 в диапазоне30000..899400")
    corpus = generate(seed)
    metadata = corpus["metadata"]
    anchor = dt.datetime.fromisoformat(metadata["seed_anchor"])
    branches = SyntheticBranchDirectory().load(metadata["seed"], anchor)[:10]
    catalog = {row["code"]: row for row in yaml.safe_load((DATA / "product_lines.yaml").read_text())["product_lines"]}
    # Направление явно задаётся дизайном sample на основе обслуживаемого
    # каталога, а не угадывается из неоднозначного coarse product='credit'.
    lines = {branch.code: branch.product_line_codes[0] for branch in branches}
    metadata.update(
        version="csi_scoped_v2",
        dataset_code=f"csi_scoped_v2_{id_base}",
        id_base=id_base,
        seed_anchor=anchor.isoformat(),
        as_of=(dt.datetime.fromisoformat(metadata["as_of"]) - dt.timedelta(days=1)).isoformat(),
        observation_window={
            "start": (anchor - dt.timedelta(days=1)).isoformat(),
            "end": (anchor - dt.timedelta(days=1) + dt.timedelta(hours=8)).isoformat(),
            "bounds": "[start,end)",
        },
        branch_lines=lines,
        direction_source="declared synthetic cohort; not model classification",
        denominator_scope="only registered run + cohort + direction + complete observation window",
    )
    corpus["directory_snapshot"] = [
        {"branch_code": branch.code, "product_line_codes": branch.product_line_codes, "is_synthetic": True}
        for branch in branches
    ]
    for employee in corpus["employees"]:
        employee["tenure_position_days"] -= 1
        employee["tenure_org_days"] -= 1
    for row in corpus["complaints"]:
        number = id_base + int(row["csi_no"].split("-")[1]) - 20000
        row["csi_no"] = f"CSI-{number:06d}"
        row["ticket_code"] = f"DEMO-CSI-{number:06d}"
        row["received_at"] = (dt.datetime.fromisoformat(row["received_at"]) - dt.timedelta(days=1)).isoformat()
        row["tenure_position_days"] -= 1
        row["tenure_org_days"] -= 1
        line = catalog[lines[row["branch_code"]]]
        row["products"] = line["product_codes"]
        row["complaint_ru"] += f" Обращался по учебному направлению «{line['name_ru']}»."
    for row in corpus["visits"]:
        row["day"] = (dt.date.fromisoformat(row["day"]) - dt.timedelta(days=1)).isoformat()
        row["product_line_code"] = lines[row["branch_code"]]
    return corpus
