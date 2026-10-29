"""Финальный ответ клиенту сохраняет смысл в модели Journey."""

import pytest

from app.trace.journey import client_messages
from tests.unit.test_trace_search import TS, node


@pytest.mark.parametrize(
    "template,kind",
    [("resolved", "final"), ("gift_offer", "gift"), ("ack_received", "ack"), ("manual_reply", "status")],
)
def test_delivered_notification_kind(template: str, kind: str) -> None:
    notice = node(
        "notification",
        template_code=template,
        status="sent",
        recipient_type="client",
        sent_at=TS,
        channel_code="chat",
        body="Проверка завершена",
    )
    message = client_messages([notice])[0]
    assert message["kind"] == kind
    assert message["text_ru"] == "Проверка завершена"
    notice["data"]["status"] = "queued"
    assert client_messages([notice]) == []
