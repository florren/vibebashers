---
version: v1.1
output_schema: contracts/events/agent/decision.schema.json
model_hints: основная модель; детерминированные поля (SLA, приоритет, критичность, маршрут по правилам, needs_human) пересчитываются кодом
---
Задача: предложить план действий по классифицированному обращению. Модель предлагает — код проверяет и корректирует детерминированные поля (SLA, приоритет, маршрут по правилам, политики HITL), поэтому сосредоточься на содержании.

Фасады роутера (код вызывает их по router_action и сверяет имя с фактическими вызовами):
- route_to_department — маршрут: создать или связать тикет с командой.
- escalate_to_manager — эскалация поверх уже созданного тикета (сначала маршрут, затем руководитель).
- request_clarification — один уточняющий вопрос клиенту; второй подряд запрещён.
- notify_customer — текст клиенту вне публичного ответа. router_action none — ни маршрута, ни эскалации, ни уточнения.

Код сверяет router_action с фактическими вызовами этих фасадов. Расхождение повторяет фасад один раз, затем передаёт решение человеку.

Нужно решить:
1. incident_action: create (новая проблема) / link_existing (в контексте есть открытый инцидент с тем же error_code/системой за последние 4 сим-часа или инцидент этого клиента по той же причине — укажи link_incident_id) / none (gratitude, suggestion, info_request без проблемы).
2. incident_type (как signal_type; для подтверждённой ошибочной комиссии — fee_refund), title_ru (≤ 120 символов, без ПДн).
3. complexity (easy/medium/hard; instant — только для fee_refund) и criticality (low/medium/high) — предложение, код сверит с правилами §8.1.
4. route.team — команда-владелец системы/проблемы (подсказка — правила маршрутизации: {{routing_hint}}); co_teams — при необходимости (например team_cx при репутационных рисках).
5. client_action: kind (reply / acknowledge / request_data / public_reply_and_dm для канала social или review_portal / proactive_notice / none), channel, text_ru — текст клиенту в тоне сегмента {{segment}}: извинение (если уместно), что уже делаем, когда ответим (только в рамках SLA первого ответа {{first_response_min}} мин и срока устранения), приглашение в личный канал для публичных ответов. Без обвинений, без обещаний вне SLA, без ПДн. Для request_data — question_ru (один вопрос).
6. team_notice_ru — короткое сообщение команде: что сломано, какой error_code, сколько клиентов, что проверить.
7. gift — только после resolved и только при реальной проблеме (не для info_request/gratitude): bonus_points 300/600/1000 по критичности; привилегия партнёра — только vip/ultra_vip (политика §8.5).
8. followup — если ждём данных клиента/команды или проверки фикса: wake_in_sim_hours и reason.
9. needs_human + human_reason/human_options/human_recommendation — по политикам §9.3 (ultra_vip; legal_regulatory; fraud > 50 000 ₽; привилегия партнёра; повтор 3+; конфликт классификаций; уверенность < 0,75).
10. router_action — route (создаём/линкуем тикет), escalate (плюс эскалация руководителю при churn_threat с negativity ≥ 80, повторе с негативом, severity critical, 3+ обращений за 7 дней — заполни escalation{reason, severity, to_role}), request_clarification (один вопрос — clarification_question_ru), none.
11. rationale_ru — 2–3 предложения почему так; policy_checks — список проверенных политик {rule, passed, note}.

Классификация: {{classification}}
Нормализация: {{normalization}}
Контекст: {{context}}
Канал: {{channel}}. Текст обращения: «{{text}}»
