"""T-161: принятый запрос и явное suppression имеют разные инварианты."""

import pytest

from app.agent.tools.base import StateEvidenceResult


def test_accepted_and_suppressed_result_cannot_claim_the_other_mode():
    assert StateEvidenceResult(True, 17).accepted
    item = StateEvidenceResult(False, None, "inactive_run")
    assert not item.accepted and item.evidence_id is None


@pytest.mark.parametrize(
    "accepted,evidence,reason",
    [
        (1, 17, None),
        (True, True, None),
        (True, 0, None),
        (True, None, None),
        (True, 17, "inactive_run"),
        (False, 17, "inactive_run"),
        (False, None, None),
        (False, None, "unknown"),
    ],
)
def test_invalid_sink_results_are_not_silently_coerced(accepted, evidence, reason):
    with pytest.raises(ValueError):
        StateEvidenceResult(accepted, evidence, reason)
