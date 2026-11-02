"""Script config validation не читает секреты/DB и не вводит fallback timings."""

from types import SimpleNamespace

import pytest
from psycopg.pq import TransactionStatus

from app.sim.proactive_scenario import ScriptedScenarioError, plan, prepare
from tests.integration.test_proactive_prepare import scenario


@pytest.mark.parametrize(
    "invalid",
    [
        "missing_duration",
        "empty_script",
        "cohort121",
        "complaints31",
        "notices89",
        "mode",
        "timing",
        "template",
        "secret_error",
    ],
)
async def test_invalid_script_is_constant_error_before_side_effects(invalid):
    data = scenario()
    sentinel = "synthetic-private-input"
    if invalid == "missing_duration":
        del data["fault"]["expected_duration_min"]
    elif invalid == "empty_script":
        data["script"] = {}
    elif invalid == "cohort121":
        data["fault"]["affected_clients"] = 121
    elif invalid == "complaints31":
        data["script"]["complaints"] = 31
    elif invalid == "notices89":
        data["script"]["minimum_notices"] = 89
    elif invalid == "mode":
        data["script"]["source_mode"] = "ambient"
    elif invalid == "timing":
        data["script"]["initial_step_min"] = 0
    elif invalid == "template":
        data["complaint_templates"][0]["text"] = ""
    else:
        data["script"]["complaints"] = sentinel
    with pytest.raises(ScriptedScenarioError) as captured:
        plan(data)
    assert sentinel not in str(captured.value)


def test_script_source_hash_covers_text_and_empty_script_never_falls_back():
    data = scenario()
    first = plan(data)
    data["complaint_templates"][0]["text"] += " Повторное описание."
    assert plan(data).sha256 != first.sha256
    assert plan({"id": "ordinary"}) is None
    with pytest.raises(ScriptedScenarioError):
        plan({"id": "ordinary", "script": None})


@pytest.mark.asyncio
async def test_autocommit_without_outer_transaction_fails_before_first_statement():
    class Bomb:
        autocommit = True
        info = SimpleNamespace(transaction_status=TransactionStatus.IDLE)

        async def execute(self, *_args):
            raise AssertionError("SQL до admission внешней TX")

    with pytest.raises(ValueError, match="внешнюю tick transaction"):
        await prepare(Bomb(), 1, plan(scenario()))
