"""Live acceptance и paused native preparation не останавливают чужой clock."""

import subprocess

import pytest

from tests.unit.test_ci_compose import compose


def scripted(monkeypatch, responses):
    calls = []
    pending = iter(responses)

    def request(base, path, body=None):
        calls.append((base, path, body))
        return next(pending)

    monkeypatch.setattr(compose, "_json_request", request)
    monkeypatch.setattr(compose.time, "sleep", lambda _: None)
    return calls


def test_own_run_is_paused_then_all_agent_pages_are_drained(monkeypatch):
    calls = scripted(
        monkeypatch,
        [
            {"current_run_id": 7, "running": True},
            {"current_run_id": 7, "running": False},
            {"items": [{"outcome": None}], "next_cursor": "second"},
            {"items": [{"outcome": "deferred"}], "next_cursor": None},
            {"items": [{"outcome": "failed"}], "next_cursor": "second"},
            {"items": [{"outcome": "awaiting_human"}], "next_cursor": None},
        ],
    )
    compose.prepare_scenarios("http://127.0.0.1:18428", 7)
    assert len(calls) == 6
    assert [body for _, _, body in calls if body is not None] == [{"action": "pause"}]
    assert all("run_id=7" in path for _, path, _ in calls[2:])
    assert "cursor=second" in calls[3][1] and "cursor=second" in calls[5][1]


@pytest.mark.parametrize("owned,current", [(None, 7), (7, 8)])
def test_foreign_active_owner_is_never_paused(monkeypatch, owned, current):
    calls = scripted(monkeypatch, [{"current_run_id": current, "running": True}])
    with pytest.raises(RuntimeError):
        compose.prepare_scenarios("http://127.0.0.1:18428", owned)
    assert len(calls) == 1 and calls[0][2] is None


@pytest.mark.parametrize(
    "state",
    [
        {"current_run_id": 7, "running": True},
        {"current_run_id": 8, "running": False},
        {"current_run_id": 7},
    ],
)
def test_unconfirmed_pause_blocks_scenarios(monkeypatch, state):
    calls = scripted(monkeypatch, [{"current_run_id": 7, "running": True}, state])
    with pytest.raises(RuntimeError, match="pause"):
        compose.prepare_scenarios("http://127.0.0.1:18428", 7)
    assert len(calls) == 2


def test_lite_without_owner_does_not_send_pause(monkeypatch):
    calls = scripted(monkeypatch, [{"current_run_id": None, "running": False}])
    compose.prepare_scenarios("http://127.0.0.1:18428", None)
    assert len(calls) == 1


def test_cursor_cycle_fails_instead_of_skipping_active_agents(monkeypatch):
    scripted(
        monkeypatch,
        [
            {"current_run_id": 7, "running": False},
            {"items": [], "next_cursor": "loop"},
            {"items": [], "next_cursor": "loop"},
        ],
    )
    with pytest.raises(ValueError, match="cursor"):
        compose.prepare_scenarios("http://127.0.0.1:18428", None)


def test_active_agent_drain_has_deadline(monkeypatch):
    scripted(
        monkeypatch,
        [
            {"current_run_id": 7, "running": False},
            {"items": [{"outcome": None}], "next_cursor": None},
        ],
    )
    clock = iter([0, 0, 0, 1])
    monkeypatch.setattr(compose.time, "monotonic", lambda: next(clock))
    with pytest.raises(TimeoutError, match="drain"):
        compose.prepare_scenarios("http://127.0.0.1:18428", None, timeout=1)


def test_inputs_wait_for_native_scenarios_and_pause_follows_live_acceptance(monkeypatch):
    events = []
    monkeypatch.setattr(compose.subprocess, "run", lambda command, **kwargs: events.append(command[5:]))
    monkeypatch.setattr(compose, "prepare_scenarios", lambda base, owner: events.append(["pause", owner]))
    compose.browser_phases({"E2E_BASE_URL": "http://127.0.0.1:18428"}, 7)
    assert events == [
        ["--project=read-only", "--project=settings"],
        ["pause", 7],
        ["--project=scenarios", "--no-deps"],
        ["--project=inputs", "--no-deps"],
    ]


def test_failed_live_acceptance_never_reaches_pause_or_scenario_writes(monkeypatch):
    def fail(command, **kwargs):
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(compose.subprocess, "run", fail)
    monkeypatch.setattr(compose, "prepare_scenarios", lambda *args: pytest.fail("pause after failed acceptance"))
    with pytest.raises(subprocess.CalledProcessError):
        compose.browser_phases({"E2E_BASE_URL": "http://127.0.0.1:18428"}, 7)
