"""T-040: opaque LLM digest детерминирован и никогда не переносит ключевые байты в metadata."""

from __future__ import annotations

import copy
import re

import pytest

from app.sim.baseline_llm import LLMConfigDrift, fingerprint, validate


def config():
    return (
        [{"id": 2, "provider": "mock", "model": "model-b"}, {"id": 1, "provider": "mock", "model": "model-a"}],
        [(2, "gigachat", "second", True, 500, b"cipher-two"), (1, "gigachat", "first", True, 100, b"cipher-one")],
        {"main_profile_id": 1, "fast_profile_id": 2},
    )


def test_canonical_digest_ignores_json_key_and_row_order_without_mutating_inputs():
    profiles, keys, setup = config()
    before = copy.deepcopy((profiles, keys, setup))
    digest = fingerprint(profiles, keys, setup)
    assert re.fullmatch("[0-9a-f]{64}", digest)
    assert digest == fingerprint(list(reversed(profiles)), list(reversed(keys)), dict(reversed(list(setup.items()))))
    assert (profiles, keys, setup) == before
    assert "cipher" not in digest


@pytest.mark.parametrize("changed", ["model", "role", "key", "limit"])
def test_every_operator_llm_change_changes_digest(changed):
    profiles, keys, setup = config()
    before = fingerprint(profiles, keys, setup)
    if changed == "model":
        profiles[0]["model"] = "changed"
    elif changed == "role":
        setup["main_profile_id"] = 2
    elif changed == "key":
        keys[0] = (*keys[0][:-1], b"rotated-cipher")
    else:
        keys[0] = (*keys[0][:-2], 600, keys[0][-1])
    assert fingerprint(profiles, keys, setup) != before


@pytest.mark.parametrize(
    "meta", [{}, {"llm_config_fingerprint": "a" * 64}, {"llm_config_fingerprint": "a" * 64, "dump_sha256": "wrong"}]
)
def test_legacy_or_unbound_snapshot_is_explicit_refusal(meta):
    with pytest.raises(LLMConfigDrift, match="Пересоздайте"):
        validate(meta, "a" * 64, "b" * 64)


def test_unchanged_config_passes_and_drift_refuses_without_exposing_cipher_bytes():
    profiles, keys, setup = config()
    digest = fingerprint(profiles, keys, setup)
    meta = {"llm_config_fingerprint": digest, "dump_sha256": "b" * 64}
    validate(meta, digest, "b" * 64)
    with pytest.raises(LLMConfigDrift) as exc:
        validate(meta, "c" * 64, "b" * 64)
    assert "cipher-one" not in str(exc.value)


def test_plaintext_key_and_malformed_setup_are_rejected_without_echo():
    with pytest.raises(LLMConfigDrift) as exc:
        fingerprint([], [(1, "gigachat", "test", True, 1, "not-encrypted-secret")], {})
    assert "not-encrypted-secret" not in str(exc.value)
    with pytest.raises(LLMConfigDrift):
        fingerprint([], [], ["invalid"])


def test_pending_legacy_is_refused_before_reading_other_config_values():
    from unittest.mock import Mock

    from app.sim.baseline_llm import LEGACY_PENDING, read_sync

    cur = Mock()
    cur.execute.return_value.fetchone.return_value = ([], True)
    with pytest.raises(LLMConfigDrift, match=LEGACY_PENDING):
        read_sync(cur)
    assert cur.execute.call_count == 1


async def test_early_legacy_guard_reads_boolean_only_and_never_converts():
    from unittest.mock import AsyncMock

    from app.sim.baseline_llm import LEGACY_PRESENT_SQL, ensure_canonical

    conn = AsyncMock()
    conn.execute.return_value.fetchone.return_value = (True,)
    with pytest.raises(LLMConfigDrift, match="конвертирован"):
        await ensure_canonical(conn)
    assert conn.execute.await_args.args == (LEGACY_PRESENT_SQL,)
    assert "exists" in LEGACY_PRESENT_SQL and "pgp" not in LEGACY_PRESENT_SQL
