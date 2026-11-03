"""T262: deterministic source и fail-closed границы private preparation."""

import datetime as dt

import pytest

from app.ingest.csi import parse_xlsx, validate_row
from app.sim.csi_scoped_corpus import generate_scoped
from app.sim.scenario_acceptance import PreparationError, require_mock, validate_plan, workbook_bytes


def test_deterministic_workbook_passes_actual_parser():
    source = generate_scoped()
    at = dt.datetime.fromisoformat(source["metadata"]["seed_anchor"])
    rows = source["complaints"]
    first = workbook_bytes(rows, at)
    assert first == workbook_bytes(rows, at)
    assert [validate_row(r.value) for r in parse_xlsx(first)] == [validate_row(r) for r in rows]


def test_effective_mock_all_roles_required():
    require_mock({"roles": {role: {"provider": "mock"} for role in ("main", "fast", "twin")}})
    for roles in (
        {},
        {"main": {"provider": "mock"}},
        {role: {"provider": "replay" if role == "twin" else "mock"} for role in ("main", "fast", "twin")},
    ):
        with pytest.raises(PreparationError, match="effective Mock"):
            require_mock({"roles": roles})


@pytest.mark.parametrize("value", [None, {}, {"version": True}, {"version": 1, "id_base": True}, {"version": 2}])
def test_invalid_persisted_plan_is_not_reconstructed(value):
    with pytest.raises(PreparationError):
        validate_plan(value)


def test_workbook_refuses_naive_clock():
    with pytest.raises(PreparationError, match="timezone"):
        workbook_bytes([], dt.datetime(2026, 11, 9))


def test_known_plan_rejects_hash_bool_overlap_and_naive_clock():
    import copy

    base = {
        "version": 1,
        "id_base": 30000,
        "extra_id_base": 30300,
        "seed": 42,
        "clock": "2026-11-09T09:00:00+03:00",
        "closed_branch_code": "VSP-0011",
        "prepared": False,
        "xlsx_sha256": "a" * 64,
        "cohort_sha256": "b" * 64,
    }
    assert validate_plan(base) is base
    for key, value in [
        ("id_base", True),
        ("extra_id_base", 30000),
        ("seed", False),
        ("clock", "2026-11-09T09:00:00"),
        ("prepared", 0),
        ("xlsx_sha256", "z" * 64),
    ]:
        invalid = copy.deepcopy(base)
        invalid[key] = value
        with pytest.raises(PreparationError):
            validate_plan(invalid)


@pytest.mark.parametrize("key", ["legal_pending_hitl", "csi_registered_sample"])
@pytest.mark.parametrize("want", [False, 0, 1, "true", None, {}, []])
async def test_unsupported_boolean_expectation_is_not_verified_before_sql(key, want):
    from app.sim.scenario_acceptance import evaluate_native

    class NoSql:
        def cursor(self, **kwargs):
            raise AssertionError("unsupported expected не должен выполнять SQL")

    result = await evaluate_native(NoSql(), {"expected": {key: want}}, 1)
    assert result["checks"][0] == {"code": key, "ok": None, "detail": "not_verified: поддержано только expected=True"}
    assert result["counts"]["not_verified"] == 1
    assert not result["counts"]["native_passed"] and not result["passed"]
