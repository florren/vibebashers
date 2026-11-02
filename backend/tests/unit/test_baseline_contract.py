"""T-040: contract digest связывает архив с миграциями и фактической схемой."""

import pytest

from app.sim import baseline_contract as contract


def test_contract_binds_source_and_nonpublic_relations(tmp_path, monkeypatch):
    (tmp_path / "contracts/db").mkdir(parents=True)
    source = tmp_path / "contracts/db/schema.sql"
    source.write_text("create table a(id bigint);")
    (tmp_path / "backend/migrations").mkdir(parents=True)
    monkeypatch.setattr(contract, "ROOT", tmp_path)
    rows = [["public", "a", "r", [["id", "bigint", True, "", "", None]], [], []]]
    first = contract.fingerprint(rows)
    assert first == contract.fingerprint(rows)
    assert first != contract.fingerprint([*rows, ["langgraph", "checkpoints", "r", [], [], []]])
    migration = tmp_path / "backend/migrations/0012_checkpoint.sql"
    migration.write_text("create schema langgraph;")
    assert first != contract.fingerprint(rows)
    migration.unlink()
    source.write_text("create table a(id text);")
    assert first != contract.fingerprint(rows)


@pytest.mark.parametrize("metadata", [{}, {"db_contract_fingerprint": "old"}])
def test_missing_or_stale_contract_refuses_with_recovery(metadata):
    with pytest.raises(contract.ContractDrift, match="Пересоздайте baseline"):
        contract.validate(metadata, "a" * 64)
    contract.validate({"db_contract_fingerprint": "a" * 64}, "a" * 64)
