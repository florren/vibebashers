---
version: v1.0
output_schema: contracts/events/agent/instant_decision.schema.json
model_hints: один вызов основной модели на быстром пути (ТЗ 21.4); исполнение инструментов — код в act_instant
---
Задача: быстрое решение по подтверждённому бизнес-правилу (возврат комиссии и публичный ответ). Код проверит политики и выполнит инструменты в фиксированном порядке.

Нужно вернуть structured output:
1. classification — тип fee_refund / tariff_terms + tech_fault, product debit_card, error_code из правила, flags (public, rule_confirmed, churn_intent при угрозе ухода), negativity, problem_summary, confidence ≥ 0,75.
2. rule_codes — коды сработавших правил из контекста (например RULE-QR-FEE-001).
3. actions — план инструментов (operation_id и amount_rub из правила/операций): refund_fee → create_incident (fee_refund) → publish_public_reply → notify_client.
4. public_reply_ru — ответ под постом: извинение, факт возврата, приглашение в личный канал, без ПДн и обещаний вне SLA (20–700 символов).
5. client_notice_ru — личное уведомление клиенту о возврате.
6. gift — bonus_points 300 при churn_intent, иначе null или 300 баллов.
7. rationale_ru — почему автономный возврат допустим (ссылка на правило, сумма, идентификация).
8. confidence — уверенность в решении 0–1.

Сработавшие правила: {{rules_matched}}
Идентификация: {{identification}}
Контекст: {{context}}
Канал: {{channel}}. Текст: «{{text}}»
