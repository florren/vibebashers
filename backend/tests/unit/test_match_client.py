"""T-173: матчинг по косвенным данным. reviews_v1 собран здесь: отдельный файл набора T-178 не выделен."""

from __future__ import annotations

from app.agent.matching import ClientView, log_ru, match_clients
from app.agent.nodes import _contacts_hint_for_match
from app.agent.policies import PolicyContext, refund_allowed
from app.agent.state import new_state
from app.contracts.registry import validate


def _client(
    client_id: int,
    *,
    nick: str | None = None,
    last4: str | None = None,
    phone: str | None = None,
    city: str = "Воронеж",
    products: set[str] | None = None,
) -> ClientView:
    return ClientView(
        client_id=client_id,
        nicknames={nick.lstrip("@").lower()} if nick else set(),
        last4={last4} if last4 else set(),
        phone=phone,
        city=city,
        products=products or {"debit_card"},
    )


def test_contacts_hint_merges_external_nick_and_product() -> None:
    state = new_state(1, {"id": 1, "channel": "social", "text": "x"}, agent_run_id=1, prompt_version="v1")
    state["normalization"] = {
        "contacts_hint": {"masked_card_last4": "4512"},
        "entities": {"product": "debit_card"},
    }
    state["signal"]["external_contact"] = {"nick": "@reviewer"}
    hint = _contacts_hint_for_match(state, state["signal"])
    assert hint["nickname"] == "@reviewer"
    assert hint["masked_card_last4"] == "4512"
    assert hint["product"] == "debit_card"


def test_nickname_and_card_reach_autonomy_threshold() -> None:
    clients = [_client(1, nick="anna_vrn", last4="4512"), _client(2, nick="boris", last4="4512")]
    alone = match_clients(clients, {"nickname": "@anna_vrn"})
    both = match_clients(clients, {"nickname": "anna_vrn", "masked_card_last4": "4512", "city": "Воронеж"})
    assert alone["decision"] == "identified" and alone["candidates"][0]["confidence"] == 0.9
    assert both["decision"] == "identified"
    assert both["candidates"][0]["confidence"] >= 0.9
    assert both["candidates"][0]["matched_by"][:2] == ["nickname", "card_last4"]
    assert "ник + карта" in log_ru(both)
    assert validate(both, "agent/client_match") == []


def test_last4_collision_is_ambiguous_and_blocks_refund() -> None:
    clients = [_client(1, nick="anna", last4="4512"), _client(2, nick="boris", last4="4512")]
    result = match_clients(clients, {"masked_card_last4": "4512"})
    assert result["decision"] == "ambiguous"
    assert all(item["confidence"] < 0.8 for item in result["candidates"])
    ok, _why = refund_allowed(
        450,
        "mass",
        rule_confirmed=True,
        ident_conf=0.0,
        class_conf=0.9,
        already_refunded=False,
        ctx=PolicyContext(),
    )
    assert ok is False


def test_reviews_v1_matching_accuracy() -> None:
    """100 отзывов: ник и ник+карта определяются верно, коллизии last4 не становятся identified."""
    clients = [_client(i, nick=f"user_{i}", last4=f"{i:04d}"[-4:]) for i in range(1, 41)]
    clients.append(_client(41, nick="shared_a", last4="7777"))
    clients.append(_client(42, nick="shared_b", last4="7777"))
    cases: list[dict[str, object]] = []
    for i in range(1, 71):
        cid = ((i - 1) % 40) + 1
        cases.append({"kind": "nick", "true_id": cid, "hint": {"nickname": f"@user_{cid}"}})
    for i in range(1, 21):
        cid = i
        cases.append(
            {
                "kind": "nick_card",
                "true_id": cid,
                "hint": {"nickname": f"user_{cid}", "masked_card_last4": f"{cid:04d}"[-4:], "product": "debit_card"},
            }
        )
    for _ in range(10):
        cases.append({"kind": "collision", "true_id": None, "hint": {"masked_card_last4": "7777"}})
    assert len(cases) == 100

    correct = 0
    eligible = 0
    false_identified = 0
    for case in cases:
        result = match_clients(clients, case["hint"])  # type: ignore[arg-type]
        identified = result["decision"] == "identified"
        winner = result["candidates"][0]["client_id"] if identified else None
        if identified and winner != case["true_id"]:
            false_identified += 1
        if case["kind"] == "collision":
            assert result["decision"] == "ambiguous"
        else:
            eligible += 1
            if winner == case["true_id"]:
                correct += 1
    assert false_identified == 0
    assert correct / eligible >= 0.9
