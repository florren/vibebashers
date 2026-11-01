"""Связь определяется проблемой, а не только клиентом и общим типом."""

from app.agent.nodes import matching_incident


def test_distinct_errors_of_same_client_remain_separate():
    incident = {"is_clients": True, "incident_type": "tech_fault", "error_code": "APP-CRASH-PAY"}
    assert matching_incident([incident], {"error_code": "DEP-TIMEOUT-503"}, "tech_fault") is None


def test_same_error_links_other_clients():
    incident = {"is_clients": False, "error_code": "DEP-TIMEOUT-503"}
    assert matching_incident([incident], {"error_code": "DEP-TIMEOUT-503"}, "tech_fault") == incident


def test_missing_error_requires_product_system_and_problem_overlap():
    incident = {
        "is_clients": True,
        "incident_type": "tech_fault",
        "product": "deposit",
        "system": "mobile_app",
        "title": "Ошибка открытия депозита",
    }
    classification = {
        "product": "deposit",
        "system": "mobile_app",
        "summary_ru": "Ошибка открытия депозита повторилась",
    }
    assert matching_incident([incident], classification, "tech_fault") == incident
    assert matching_incident([{**incident, "is_clients": False}], classification, "tech_fault") is None
    assert matching_incident([incident], {**classification, "summary_ru": "Потерялись документы"}, "tech_fault") is None
    assert matching_incident([incident], {**classification, "product": "credit_card"}, "tech_fault") is None


def test_generic_summary_uses_original_problem_and_distinguishes_numbers():
    incident = {
        "is_clients": True,
        "incident_type": "tech_fault",
        "product": "deposit",
        "system": "mobile_app",
        "title": "Техническая проблема",
        "source_text": "Не могу открыть вклад в мобильном приложении: после подтверждения ошибка 503",
    }
    classification = {"product": "deposit", "system": "mobile_app", "summary_ru": "Техническая проблема"}
    assert (
        matching_incident(
            [incident], classification, "tech_fault", "Повторно: ошибка 503 при открытии вклада в мобильном приложении"
        )
        == incident
    )
    assert (
        matching_incident(
            [incident], classification, "tech_fault", "Ошибка 500 при открытии вклада в мобильном приложении"
        )
        is None
    )


def test_original_problem_can_link_other_clients_without_error_code():
    incident = {
        "is_clients": False,
        "incident_type": "tech_fault",
        "product": "deposit",
        "system": "mobile_app",
        "title": "Техническая проблема",
        "source_text": "Не могу открыть вклад в мобильном приложении: ошибка 503",
    }
    classification = {"product": "deposit", "system": "mobile_app", "summary_ru": "Техническая проблема"}
    assert (
        matching_incident(
            [incident], classification, "tech_fault", "Ошибка 503 при открытии вклада в мобильном приложении"
        )
        == incident
    )


def test_payment_crash_requires_payment_context():
    from app.agent.nodes import _text_matches_error

    assert not _text_matches_error("Не открывается вклад в мобильном приложении: ошибка503", "APP-CRASH-PAY")
    assert not _text_matches_error("Приложение зависает при открытии вклада", "APP-CRASH-PAY")
    assert _text_matches_error("Приложение закрывается при подтверждении платежа", "APP-CRASH-PAY")
    assert _text_matches_error("APP-CRASH-PAY: код ошибки", "APP-CRASH-PAY")


def test_model_payment_crash_is_not_attached_to_deposit_case():
    from types import SimpleNamespace

    from app.agent.nodes import _postcheck_classification
    from app.agent.state import new_state

    state = new_state(
        1, {"id": 1, "text": "Не открывается вклад в мобильном приложении: ошибка503", "channel": "chat"}, 1, "v1.1"
    )
    state["context"] = {"hints": {"error_code": "APP-CRASH-PAY", "system": "mobile_app"}, "products": []}
    cls, _ = _postcheck_classification(
        {
            "signal_type": "tech_fault",
            "product": "deposit",
            "system": "mobile_app",
            "error_code": "APP-CRASH-PAY",
            "summary_ru": "Не открывается вклад",
        },
        state,
        SimpleNamespace(teams=["team_cx"], policies={}, routing_rules=[]),
    )
    assert cls["error_code"] is None
    assert cls["product"] == "deposit" and cls["signal_type"] == "tech_fault"
