"""Дорожка конкретного клиента не включает доставки другим участникам инцидента."""

from __future__ import annotations

from app.trace.assembler import render
from app.trace.journey import build_journey, client_messages

TS = "2026-11-02T09:00:00+00:00"


def test_signal_client_lane_does_not_show_another_clients_delivery():
    subject = {
        "kind": "signal",
        "scope_id": 2,
        "data": {"id": 1, "public_id": "SIG-000001", "client_id": 10, "status": "answered", "received_at": TS},
    }

    def notification(identifier, client, status="sent"):
        return {
            "kind": "notification",
            "scope_id": 2,
            "data": {
                "id": identifier,
                "public_id": f"NTF-{identifier:06d}",
                "client_id": client,
                "signal_id": None,
                "incident_id": 7,
                "recipient_type": "client",
                "status": status,
                "channel_code": "chat",
                "template_code": "gift",
                "body": f"Сообщение{identifier}",
                "created_at": TS,
                "sent_at": TS,
            },
        }

    nodes = [subject, notification(1, 10), notification(2, 20), notification(3, 10, "queued")]
    result = build_journey(render(subject, [], nodes[1:], []), nodes)
    assert [m["text_ru"] for m in result["client_lane"]] == ["Сообщение1"]


def test_signal_lane_does_not_show_other_clients_posts_or_reactions():
    subject = {"kind": "signal", "data": {"id": 1, "client_id": 10, "external_post_id": 7}}
    nodes = [subject]
    for identifier, post in [(1, 7), (2, 8)]:
        nodes.append(
            {
                "kind": "reply",
                "data": {
                    "id": identifier,
                    "post_id": post,
                    "author": "agent",
                    "text": f"Ответ{identifier}",
                    "published_at": TS,
                },
            }
        )
    for identifier, client in [(1, 10), (2, 20)]:
        nodes.append(
            {
                "kind": "reaction",
                "data": {"id": identifier, "client_id": client, "text": f"Реакция{identifier}", "created_at": TS},
            }
        )
    assert [m["text_ru"] for m in client_messages(nodes)] == ["Ответ1", "Реакция1"]


def test_anonymous_signal_only_sees_its_own_unidentified_delivery():
    subject = {"kind": "signal", "data": {"id": 1, "client_id": None}}
    nodes = [subject]
    for sid in [1, 2]:
        nodes.append(
            {
                "kind": "notification",
                "data": {
                    "signal_id": sid,
                    "client_id": None,
                    "recipient_type": "client",
                    "status": "sent",
                    "sent_at": TS,
                    "channel_code": "chat",
                    "body": f"Доставка{sid}",
                },
            }
        )
    assert [m["text_ru"] for m in client_messages(nodes)] == ["Доставка1"]
