"""T039 B: strict immutable provenance; отсутствие значения не означает нулевой факт."""

from __future__ import annotations

import datetime as dt
from dataclasses import replace

import pytest

from app.sim.behavior.cancellation_details import CancellationDetails

NOW = dt.datetime(2026, 11, 2, 9, tzinfo=dt.UTC)


def example() -> CancellationDetails:
    return CancellationDetails(
        episode_no=1,
        work_kind="complaint",
        due_sim=NOW + dt.timedelta(hours=1),
        cancellation_sim=NOW,
        cancellation_observed_sim=NOW + dt.timedelta(minutes=15),
        first_complaint_sim_at_cancellation=None,
        complaint_observation_complete=True,
        evidence_id=2,
        evidence_kind="resolution",
        evidence_source_id=3,
        canonical_signal_id=None,
        resolution_sim=NOW - dt.timedelta(minutes=1),
    )


def test_roundtrip_preserves_logical_observation_resolution_and_unknown():
    original = example()
    assert CancellationDetails.from_json(original.to_json()) == original
    assert original.cancellation_observed_sim > original.cancellation_sim > original.resolution_sim
    assert original.action == "cancelled_by_resolution"
    unknown = replace(original, resolution_sim=None, complaint_observation_complete=False)
    assert CancellationDetails.from_json(unknown.to_json()) == unknown
    assert unknown.to_json()["resolution_sim"] is None
    assert unknown.to_json()["complaint_observation_complete"] is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("episode_no", True),
        ("episode_no", 0),
        ("episode_no", 2**31),
        ("evidence_id", False),
        ("evidence_id", 1.0),
        ("evidence_source_id", -1),
        ("canonical_signal_id", True),
        ("evidence_id", 2**63),
        ("work_kind", "gift"),
        ("evidence_kind", "notification"),
        ("complaint_observation_complete", 1),
        ("due_sim", NOW.replace(tzinfo=None)),
        ("resolution_sim", NOW + dt.timedelta(seconds=1)),
        ("first_complaint_sim_at_cancellation", NOW + dt.timedelta(seconds=1)),
        ("cancellation_observed_sim", NOW - dt.timedelta(seconds=1)),
    ],
)
def test_invalid_native_values_are_rejected(field, value):
    with pytest.raises(ValueError):
        replace(example(), **{field: value})


@pytest.mark.parametrize(
    "change",
    [
        {"version": True},
        {"version": 2},
        {"extra": "client text must not be stored"},
        {"due_sim": "2026-11-02T09:00:00"},
        {"due_sim": "2026-02-30T09:00:00Z"},
        {"episode_no": True},
        {"work_kind": "x" * 3000},
    ],
)
def test_invalid_json_is_rejected_without_coercion(change):
    with pytest.raises(ValueError):
        CancellationDetails.from_json(example().to_json() | change)


def test_already_complained_requires_canonical_source_and_has_no_resolution_credit():
    details = replace(
        example(),
        evidence_kind="agent_state",
        canonical_signal_id=4,
        first_complaint_sim_at_cancellation=NOW,
        resolution_sim=None,
    )
    assert details.action == "already_complained"
    assert CancellationDetails.from_json(details.to_json()) == details
    for change in (
        {"canonical_signal_id": None},
        {"work_kind": "repeat"},
        {"first_complaint_sim_at_cancellation": None},
        {"resolution_sim": NOW},
    ):
        with pytest.raises(ValueError):
            replace(details, **change)
