"""Directed, allowlisted causal relations (ТЗ 28.4); identifiers never come from requests."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ObjectType:
    table: str
    event: str
    title: str
    actor: str = "system"
    key: str = "id"
    public: str = "public_id"


TYPES = {
    "signal": ObjectType("signals", "signal_created", "Сигнал принят"),
    "incident": ObjectType("incidents", "incident_created", "Инцидент создан"),
    "client": ObjectType("clients", "client_identified", "Клиент", "client"),
    "post": ObjectType("external_posts", "source_message", "Пост клиента", "client"),
    "transcript": ObjectType("transcripts", "source_message", "Транскрипт"),
    "audio_session": ObjectType("audio_sessions", "source_message", "Аудиосессия"),
    "employee": ObjectType("employees", "source_message", "Сотрудник"),
    "branch": ObjectType("branches", "source_message", "Отделение", public="code"),
    "agent_run": ObjectType("agent_runs", "decision", "Запуск агента", "agent"),
    "sim_run": ObjectType("sim_runs", "source_message", "Запуск эмуляции", "sim"),
    "task": ObjectType("tasks", "task", "Задача", "human"),
    "notification": ObjectType("notifications", "notification", "Уведомление"),
    "ledger": ObjectType("ledger_entries", "fee", "Проводка"),
    "human_decision": ObjectType("human_decisions", "human_request", "Решение человека", "human"),
    "followup": ObjectType("followups", "followup", "Отложенное действие"),
    "escalation": ObjectType("escalations", "escalation", "Эскалация", "human"),
    "rule": ObjectType("business_rules", "rule_evaluation", "Бизнес-правило", key="code", public="code"),
    "error_code": ObjectType("error_codes", "fault", "Код ошибки", key="code", public="code"),
    "csi": ObjectType("csi_responses", "source_message", "CSI-обращение", key="signal_id", public="csi_no"),
    "ingest": ObjectType("ingest_messages", "source_message", "Сообщение принято", public="id"),
    "operation": ObjectType("operations", "operation", "Операция", public="id"),
    "fault": ObjectType("faults", "fault", "Сбой", public="id"),
    "step": ObjectType("agent_steps", "tool_call", "Шаг агента", "agent", public="id"),
    "evaluation": ObjectType("rule_evaluations", "rule_evaluation", "Правило проверено", "agent", public="id"),
    "team_action": ObjectType("team_actions", "team_action", "Действие команды", "team", public="id"),
    "status_history": ObjectType("incident_status_history", "incident_status", "Статус инцидента", public="id"),
    "artifact": ObjectType("incident_artifacts", "team_action", "Отчёт команды", "team", public="id"),
    "reply": ObjectType("external_replies", "public_reply", "Публичный ответ", "agent", public="id"),
    "reaction": ObjectType("client_reactions", "client_reaction", "Реакция клиента", "client", public="id"),
    "economics": ObjectType(
        "incident_economics", "economics", "Экономика обращения", key="incident_id", public="incident_id"
    ),
    "churn": ObjectType("churn_events", "churn", "Уход клиента", "client", public="id"),
    "alert": ObjectType("compliance_alerts", "compliance_alert", "Алерт руководителю", public="id"),
}

# source kind, target kind, equality predicate on aliases a/b. Causality is independent of FK direction.
RELATIONS: list[tuple[str, str, str]] = [
    ("ingest", "signal", "a.signal_id = b.id"),
    ("post", "signal", "a.id = b.external_post_id"),
    ("transcript", "signal", "a.id = b.transcript_id"),
    ("audio_session", "transcript", "a.id = b.audio_session_id"),
    ("csi", "signal", "a.signal_id = b.id"),
    ("operation", "signal", "a.id = b.source_operation_id"),
    ("fault", "signal", "a.id = b.source_fault_id"),
    ("fault", "operation", "a.id = b.fault_id"),
    ("operation", "ledger", "a.id = b.operation_id AND b.kind = 'fee'"),
    ("ledger", "signal", "a.operation_id = b.source_operation_id AND a.kind = 'fee'"),
    ("signal", "signal", "a.id = b.parent_signal_id"),
    ("client", "signal", "a.id = b.client_id"),
    ("branch", "transcript", "a.id = b.branch_id"),
    ("employee", "transcript", "a.id = b.employee_id"),
    ("signal", "agent_run", "a.id = b.signal_id"),
    ("agent_run", "step", "a.id = b.run_id"),
    ("signal", "evaluation", "a.id = b.signal_id"),
    ("agent_run", "evaluation", "a.id = b.agent_run_id"),
    ("rule", "evaluation", "a.code = b.rule_code"),
    ("signal", "human_decision", "a.id = b.signal_id"),
    ("agent_run", "human_decision", "a.id = b.agent_run_id"),
    ("signal", "escalation", "a.id = b.signal_id"),
    ("human_decision", "escalation", "a.id = b.human_decision_id"),
    ("agent_run", "incident", "a.id = b.agent_run_id"),
    ("step", "incident", "a.run_id = b.agent_run_id AND a.started_at <= b.created_at"),
    ("incident", "step", "a.agent_run_id = b.run_id AND b.started_at > a.created_at"),
    ("fault", "incident", "a.id = b.fault_id"),
    ("incident", "incident", "a.id = b.duplicate_of_id"),
    ("error_code", "incident", "a.code = b.error_code"),
    (
        "signal",
        "incident",
        "EXISTS (SELECT 1 FROM incident_signals x WHERE x.signal_id=a.id AND x.incident_id=b.id AND x.linked_sim <= b.created_sim)",
    ),
    (
        "incident",
        "signal",
        "EXISTS (SELECT 1 FROM incident_signals x WHERE x.incident_id=a.id AND x.signal_id=b.id AND x.linked_sim > a.created_sim)",
    ),
    ("ledger", "ledger", "a.id = b.refund_of_entry_id"),
    ("agent_run", "ledger", "a.id = b.agent_run_id"),
    ("post", "reply", "a.id = b.post_id"),
    ("agent_run", "reply", "a.id = b.agent_run_id"),
    ("audio_session", "alert", "a.id = b.session_id"),
    ("incident", "churn", "a.id = ANY(b.related_incident_ids)"),
]
for child in (
    "team_action",
    "status_history",
    "artifact",
    "task",
    "notification",
    "followup",
    "economics",
    "reaction",
    "human_decision",
    "escalation",
    "reply",
):
    RELATIONS.append(("incident", child, "a.id = b.incident_id"))
for child in ("notification", "followup", "reaction"):
    RELATIONS.append(("signal", child, "a.id = b.signal_id"))
RELATIONS.append(("notification", "reaction", "a.id = b.notification_id"))

MATRIX = {
    kind: {"before": [a for a, b, _ in RELATIONS if b == kind], "after": [b for a, b, _ in RELATIONS if a == kind]}
    for kind in TYPES
}
