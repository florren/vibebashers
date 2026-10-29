"""Воспроизводимые синтетические контрольные исходы T-265; не измерение качества реальной NLP."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.economics.calibration import fit
from app.sim.rng import SimRng


def main() -> None:
    rng = SimRng(265)
    rows = []
    for split in ("train", "validation"):
        for b in range(5):
            for index in range(200):
                score = rng.randint(b * 20, min(100, b * 20 + 19))
                probability = 0.02 + 0.8 * (score / 100) ** 1.5
                rows.append(
                    {
                        "client_ref": f"SYN-{split}-{b}-{index:04d}",
                        "split": split,
                        "scope": "demo",
                        "model": "mock:mock-rules-v1",
                        "prompt_version": "v1.1",
                        "score_pipeline": "agent-score-v1",
                        "score": score,
                        "horizon_days": 7,
                        "predicted_sim": "2026-10-01T00:00:00Z",
                        "observed_until_sim": "2026-10-08T00:00:00Z",
                        "churned_sim": "2026-10-05T00:00:00Z"
                        if rng.random() < probability
                        else None,
                        "treated": False,
                    }
                )
    metadata = {
        "id": "demo-mock-7d-v1",
        "scope": "demo",
        "data_kind": "synthetic_controls",
        "model": "mock:mock-rules-v1",
        "prompt_version": "v1.1",
        "horizon_days": 7,
        "cutoff_sim": "2026-10-08T00:00:00Z",
        "business_approval_ref": "prototype-demo-request-2026-10-29",
        "generator": "gen_churn_demo-v1-seed265",
        "population": "synthetic_retail",
    }
    out = ROOT / "data/economics"
    out.mkdir(parents=True, exist_ok=True)
    (out / "demo-controls.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    )
    (out / "demo-metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n"
    )
    (out / "demo-calibration.json").write_text(
        json.dumps(fit(rows, metadata), ensure_ascii=False, indent=2) + "\n"
    )


if __name__ == "__main__":
    main()
