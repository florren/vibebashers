"""Personal browser proof использует собственный динамический localhost port."""

from tests.unit.test_ci_compose import candidate_config, compose


def test_personal_port_is_ephemeral_and_does_not_publish_database(tmp_path, monkeypatch):
    monkeypatch.setattr(compose, "ROOT", tmp_path)
    isolated = compose.isolate(
        candidate_config(tmp_path),
        "cx-ci-personal",
        "cx-pulse-backend:ci",
        18080,
        tmp_path / "candidate",
        expose_personal=True,
    )
    assert isolated["services"]["personal"]["ports"] == [
        {"target": 9999, "published": "0", "host_ip": "127.0.0.1", "protocol": "tcp"}
    ]
    assert isolated["services"]["backend"]["ports"][0]["published"] == "18080"
    assert isolated["services"]["postgres"]["ports"] == []
