"""T-106: сравнение классификации и пустой граф сущностей без инцидента."""

from fastapi.testclient import TestClient

from app.api.engine import classification_diff
from app.main import create_app


def test_classification_diff_lists_changed_fields() -> None:
    diff = classification_diff(
        {"signal_type": "churn", "sentiment": "negative"}, {"signal_type": "info_request", "sentiment": "negative"}
    )
    assert diff == [{"field": "signal_type", "llm": "churn", "mock": "info_request"}]


def test_compare_rejects_short_text() -> None:
    with TestClient(create_app()) as client:
        res = client.post("/api/agent/compare", json={"text": "а", "channel_code": "chat"})
    assert res.status_code == 422


def test_entity_graph_empty_without_ids() -> None:
    with TestClient(create_app()) as client:
        res = client.get("/api/engine/entity-graph")
    assert res.status_code == 200
    assert res.json() == {"nodes": [], "edges": []}
