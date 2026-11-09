"""Штатный seed и restore не требуют ручной подготовки совместимых копий."""

import json

import pytest

from app.sim import baseline, baseline_llm, baseline_operational


def test_new_native_publication_supersedes_stale_compatible_bundle(tmp_path, monkeypatch):
    monkeypatch.setattr(baseline, "baseline_dir", lambda: tmp_path)
    source = tmp_path / "lite.dump"
    prepared = tmp_path / "lite.compatible.dump"
    source.write_bytes(b"new native archive")
    prepared.write_bytes(b"old compatible archive")
    provenance = prepared.with_suffix(".dump.provenance.json")
    provenance.write_text(json.dumps({"source_sha256": "old", "output_sha256": baseline._sha256_file(prepared)}))
    before = (prepared.read_bytes(), provenance.read_bytes())
    baseline._write_artifacts("lite", source, {"llm_config_fingerprint": "a" * 64, "db_contract_fingerprint": "b" * 64})
    assert baseline._restore_dump_path("lite") == source
    assert before == (prepared.read_bytes(), provenance.read_bytes())
    source.write_bytes(b"tampered native")
    with pytest.raises(baseline.BaselineToolingError, match="суммы"):
        baseline._restore_dump_path("lite")


def test_archive_binding_is_required_even_when_runtime_configuration_is_preserved():
    meta = {"llm_config_fingerprint": "a" * 64, "dump_sha256": "b" * 64}
    baseline_llm.validate_archive(meta, "b" * 64)
    with pytest.raises(baseline_llm.LLMConfigDrift):
        baseline_llm.validate_archive(meta, "c" * 64)
    with pytest.raises(baseline_llm.LLMConfigDrift):
        baseline_llm.validate_archive({"dump_sha256": "b" * 64}, "b" * 64)


def test_bank_toc_excludes_operational_objects_and_keeps_bank_references():
    protected = [
        "1; 2615 1 SCHEMA - llm_runtime cx",
        "2; 0 0 COMMENT - SCHEMA channel_runtime cx",
        "3; 1259 3 TABLE llm_runtime credentials cx",
        "4; 0 3 TABLE DATA channel_runtime telegram_deliveries cx",
        "5; 1259 5 TABLE public llm_profiles cx",
        "6; 0 0 COMMENT public COLUMN llm_api_keys.credential_uid cx",
        "7; 0 0 COMMENT public TABLE llm_cassettes cx",
        "8; 0 5 TABLE DATA public llm_profiles cx",
        "9; 0 0 SEQUENCE SET public llm_api_keys_id_seq cx",
        "10; 2606 10 CONSTRAINT public llm_profiles llm_profiles_code_key cx",
        "11; 2615 11 SCHEMA - public cx",
    ]
    bank = [
        "12; 1259 12 TABLE public clients cx",
        "13; 0 12 TABLE DATA public clients cx",
        "14; 0 0 COMMENT public COLUMN agent_runs.llm_profiles_snapshot cx",
        "15; 2606 15 FK CONSTRAINT public agent_runs agent_runs_llm_profile_id_fkey cx",
        "16; 1259 16 TABLE public llm_profiles_history cx",
    ]
    result = baseline_operational.bank_toc("\n".join(protected + bank)).splitlines()
    assert result == [";" + line for line in protected] + bank
