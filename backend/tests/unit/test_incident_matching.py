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
    assert matching_incident([incident], {**classification, "summary_ru": "Потерялись документы"}, "tech_fault") is None
    assert matching_incident([incident], {**classification, "product": "credit_card"}, "tech_fault") is None
