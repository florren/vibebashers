"""T-247: воспроизводимый синтетический корпус; без БД, сети и runtime policy."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import yaml

from app.sim.rng import SimRng

DATA = Path(__file__).resolve().parents[3] / "data"


def generate(seed: int | None = None) -> dict[str, Any]:
    params = yaml.safe_load((DATA / "csi_params.yaml").read_text())
    catalog = yaml.safe_load((DATA / "branches.yaml").read_text())
    if params["synthetic"] is not True:
        raise ValueError("CSI corpus допускает только synthetic=true")
    seed = params["seed"] if seed is None else seed
    rng = SimRng(seed)
    as_of = dt.datetime.fromisoformat(params["as_of"])
    if as_of.tzinfo is None:
        raise ValueError("as_of требует timezone")
    branches = catalog["branches"]
    # EMP IDs здесь — fixture bindings чистого исходного seed. Экспорт в
    # существующий стенд требует проверки roster, а не предположения об ID.
    employees = []
    for branch_index, branch in enumerate(branches):
        for desk in range(1, branch["desks"] + 1):
            employees.append(
                {
                    "branch_code": branch["code"],
                    "desk_no": desk,
                    "employee_public_id": f"EMP-{branch_index * 6 + desk:05d}",
                    "position": catalog["positions"][desk - 1],
                    "tenure_position_days": 275 + desk * 73,
                    "tenure_org_days": 365 + desk * 73,
                }
            )
    complaints: list[dict[str, Any]] = []
    visits = []
    for wait in params["wait_buckets"]:
        for redirects in params["redirects_buckets"]:
            for branch in branches:
                visits.append(
                    {
                        "branch_code": branch["code"],
                        "day": as_of.date().isoformat(),
                        "wait_bucket": wait["code"],
                        "redirects_bucket": redirects["code"],
                        "visits": params["visits_per_branch_cell"],
                    }
                )
            count = params["complaints_per_weight"] * wait["weight"] * redirects["weight"]
            if count > len(branches) * params["visits_per_branch_cell"]:
                raise ValueError("жалоб больше посещений в корзине")
            offset = rng.randrange(len(branches))
            for index in range(count):
                branch_index = (index + offset) % len(branches)
                desk = rng.choice(params["complaint_desks"])
                staff = employees[branch_index * 6 + desk - 1]
                minutes = round(rng.uniform(wait["low"], wait["high"] - 0.01), 2)
                number = 20001 + len(complaints)
                text = (
                    f"{rng.choice(params['openings'])} {rng.choice(params['details'])} "
                    f"Ожидание по учебному талону составило {minutes:g} мин."
                )
                complaints.append(
                    {
                        "csi_no": f"CSI-{number:06d}",
                        "complaint_ru": text,
                        "branch_code": staff["branch_code"],
                        "employee_public_id": staff["employee_public_id"],
                        "position": staff["position"],
                        "tenure_position_days": staff["tenure_position_days"],
                        "tenure_org_days": staff["tenure_org_days"],
                        "received_at": (as_of + dt.timedelta(minutes=rng.randrange(480))).isoformat(),
                        "ticket_code": f"DEMO-CSI-{number:06d}",
                        "waiting_count": rng.randrange(1, 20),
                        "serving_count": rng.randrange(1, 7),
                        "out_of_order_count": rng.randrange(4),
                        "wait_min": minutes,
                        "service_min": round(rng.uniform(2, 25), 2),
                        "redirects": rng.randrange(redirects["low"], redirects["high"]),
                        "products": [rng.choice(params["products"])],
                        "feedback_type": "жалоба",
                        "topic": "вежливость/доброжелательность",
                        "subtopic": "общение сотрудника и порядок обслуживания",
                    }
                )
    return {
        "metadata": {
            "version": params["version"],
            "synthetic": True,
            "label_ru": "демонстрационные данные",
            "seed": seed,
            "seed_anchor": params["as_of"],
            "as_of": (as_of + dt.timedelta(hours=8)).isoformat(),
            "observation_window": {
                "start": as_of.isoformat(),
                "end": (as_of + dt.timedelta(hours=8)).isoformat(),
                "bounds": "[start,end)",
            },
            "employee_binding": "fresh baseline seed only; validate branch + desk + public_id before import",
            "denominator_scope": "this synthetic corpus only; not all real branch visits or arbitrary runs",
            "sampling": "fixed weighted cell counts; seeded text/time variation, not observed causal evidence",
        },
        "complaints": complaints,
        "visits": visits,
        "employees": employees,
    }
