"""Business projections: raw prompts, responses and tool arguments never leave this module."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from app.trace.privacy import mask
from app.trace.relations import TYPES

STEP_KINDS = {
    "ingest": ("source_message", "Сообщение поступило"),
    "normalize": ("signal_normalized", "Обращение понято"),
    "identify_client": ("client_identified", "Клиент определён"),
    "gather_context": ("client_identified", "Контекст клиента собран"),
    "check_rules": ("policy_check", "Правила и политики проверены"),
    "classify": ("classification", "Проблема определена"),
    "decide": ("decision", "Путь решения выбран"),
    "instant_decide": ("decision", "Быстрое решение принято"),
    "apply_human_decision": ("human_decision", "Решение человека применено"),
    "twin_react": ("client_reaction", "Реакция двойника клиента"),
    "wait_human": ("human_request", "Ожидаем решения человека"),
    "act": ("tool_call", "Действие выполнено"),
    "act_instant": ("tool_call", "Быстрое решение исполнено"),
    "followup_monitor": ("followup", "Назначена проверка"),
    "verify": ("incident_status", "Решение проверено"),
    "close": ("terminal", "Обработка завершена"),
    "gift": ("gift", "Рассмотрена благодарность клиенту"),
}
OUTCOMES = {
    "closed_in_sla_with_gift": "Закрыт в срок, подарок выдан",
    "closed_in_sla": "Закрыт в срок",
    "closed_late": "Закрыт с нарушением срока",
    "closed_with_regression": "Закрыт с регрессией",
    "churned": "Клиент ушёл",
    "rejected": "Обращение отклонено",
    "duplicate": "Дубликат",
    "noise": "Не требует обработки",
    "answered": "Клиенту ответили",
    "closed": "Обращение закрыто",
    "completed": "Обработка завершена",
    "resolved": "Решено",
    "done": "Выполнено",
}


def node_key(node: dict[str, Any]) -> str:
    return f"{node['kind']}:{node['data'][TYPES[node['kind']].key]}"


def reference(node: dict[str, Any]) -> str:
    value = str(node["data"].get(TYPES[node["kind"]].public) or node["data"][TYPES[node["kind"]].key])
    return "VSP-" + value if node["kind"] == "branch" and not value.startswith("VSP-") else value


def time_value(data: dict[str, Any], real: bool = False) -> str | None:
    keys = (
        (
            "decided_at",
            "published_at",
            "sent_at",
            "changed_at",
            "requested_at",
            "received_at",
            "posted_at",
            "started_at",
            "computed_at",
            "created_at",
        )
        if real
        else (
            "decided_sim",
            "changed_sim",
            "action_sim",
            "sent_sim",
            "posted_sim",
            "reacted_sim",
            "published_sim",
            "computed_sim",
            "requested_sim",
            "received_sim",
            "created_sim",
            "started_sim",
        )
    )
    return next((str(data[k]) for k in keys if data.get(k)), None)


def project(node: dict[str, Any], phase: str) -> dict[str, Any]:
    kind, d = node["kind"], node["data"]
    spec = TYPES[kind]
    event_kind, title = spec.event, spec.title
    if kind == "step":
        event_kind, title = STEP_KINDS.get(d["node"], ("tool_call", "Шаг обработки"))
    if kind == "human_decision" and d.get("decision"):
        event_kind, title = "human_decision", "Человек принял решение"
    if kind == "ledger":
        event_kind = "refund" if d["kind"] in ("refund", "reversal") else "fee" if d["kind"] == "fee" else "operation"
        title = (
            "Возврат выполнен" if event_kind == "refund" else "Комиссия списана" if event_kind == "fee" else "Проводка"
        )
    if kind == "task" and d["kind"] == "gift":
        event_kind, title = "gift", "Задача на подарок"
    facts = []
    for key, label in (
        ("status", "Статус"),
        ("to_status", "Новый статус"),
        ("channel_code", "Канал"),
        ("result", "Результат"),
        ("rule_code", "Правило"),
        ("rule_version", "Версия правила"),
        ("decision", "Решение"),
        ("reason", "Причина"),
        ("reaction", "Реакция"),
        ("outcome_class", "Класс исхода"),
        ("prevented_loss_rub", "Предотвращённая потеря, ₽"),
    ):
        if d.get(key) is not None:
            raw = str(d[key])
            value = mask(raw, 200)
            facts.append({"label_ru": label, "value_ru": value, "masked": value != raw})
    ref = reference(node)
    href = f"/trace/{kind}/{quote(ref, safe='')}"
    badges: dict[str, Any] = {}
    source = d.get("llm_source") or (d.get("output") or {}).get("llm_source")
    if (
        not source
        and kind == "step"
        and d["node"]
        in {"normalize", "classify", "decide", "instant_decide", "twin_react", "detect_misselling", "attribute_speaker"}
    ):
        model = str(d.get("model") or "")
        sources = {call.get("source") for call in d.get("tool_calls", [])}
        source = (
            "mock"
            if "mock" in sources or model.startswith("mock")
            else "replay"
            if "replay" in sources or model.startswith("replay/")
            else "live"
            if model
            else None
        )
    if source in ("live", "replay", "mock"):
        badges["llm_source"] = source
    if kind == "ledger":
        badges["amount_rub"] = float(d["amount"])
    brief = d.get("title") or d.get("resolution_summary") or d.get("subject") or d.get("resolution_ru") or title
    if kind in ("signal", "post", "reply", "reaction"):
        brief = d.get("text") or title
    if kind == "notification":
        brief = d.get("body") or title
    if kind == "step":
        brief = title
        if d.get("latency_ms") is not None:
            facts.append({"label_ru": "Длительность, мс", "value_ru": str(d["latency_ms"]), "masked": False})
    return {
        "id": "EVT-" + node_key(node),
        "kind": event_kind,
        "phase": phase,
        "ts_sim": time_value(d),
        "ts_real": time_value(d, True) or "1970-01-01T00:00:00Z",
        "actor": {
            "kind": spec.actor,
            "label_ru": {
                "agent": "Агент",
                "client": "Клиент",
                "human": "Человек",
                "team": "Команда",
                "system": "Система",
                "sim": "Эмулятор",
            }[spec.actor],
        },
        "object_ref": {"kind": kind, "ref": ref},
        "title_ru": mask(title, 200),
        "brief_ru": mask(brief),
        "key_facts": facts,
        "badges": badges,
        "links": {
            "trace": href,
            "journey": f"/journey/{quote(ref, safe='')}",
            "engine_step": f"/engine/{d['run_id']}?step={d['seq']}" if kind == "step" else None,
        },
        "importance": "detail" if kind == "step" and d["node"] in ("ingest", "followup_monitor") else "key",
        "run_id": f"SR-{node['scope_id']:04d}" if node.get("scope_id") else "live",
    }
