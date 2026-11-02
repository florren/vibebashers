"""Узкая semantic boundary: не credit Sent/повторы/unknown/равенство due."""

from dataclasses import replace

import pytest

from app.sim.behavior.prevention import eligible
from tests.unit.test_behavior_cancellation_details import NOW, example


@pytest.mark.parametrize(
    "change",
    [
        {"work_kind": "repeat"},
        {"work_kind": "patience"},
        {"resolution_sim": None},
        {"complaint_observation_complete": False},
        {"first_complaint_sim_at_cancellation": NOW},
        {"due_sim": NOW, "resolution_sim": NOW},
        {"due_sim": NOW.replace(hour=8), "resolution_sim": NOW},
        {
            "evidence_kind": "agent_state",
            "canonical_signal_id": 4,
            "first_complaint_sim_at_cancellation": NOW,
            "resolution_sim": None,
        },
    ],
)
def test_non_primary_late_unknown_and_already_complained_do_not_receive_credit(change):
    assert eligible(example())
    assert not eligible(replace(example(), **change))
