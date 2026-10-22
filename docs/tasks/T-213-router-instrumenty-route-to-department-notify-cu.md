# T-213 — Роутер-инструменты route_to_department / notify_customer / escalate_to_manager / request_clarification, router_action, таблица escalations, политика эскалации

| Поле | Значение |
|---|---|
| Эпик | E18 Приём транскриптов, роутер-инструменты, «красные фразы», зоны карты [ДТЗ] |
| Субагент | `SA-Agent` (агент LangGraph) |
| Оценка | L (3–4 дня) |
| Волна | 3 |
| Слой | `L3` Агент и контуры (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `done` |

## Цель
Агент принимает решение в терминах ДТЗ (маршрутизировать / эскалировать / уточнить) инструментами с точными сигнатурами поверх внутренних, с обязательной эскалацией по политике 9.3 (ДТЗ FR-3.1–3.4, ТЗ 9.2, 9.3, 9.7, решения 20.6 п. 20–21).

## Разделы ТЗ (docs/TZ.md)
§9.2, §9.3, §9.7, §13, §19, §20.6

## Контракты
- `events/agent/router_tools.schema.json`
- `events/agent/tool_call.schema.json: name, wraps`
- `events/agent/decision.schema.json: router_action, escalation, clarification_question_ru`
- `events/sim/escalation.schema.json`
- `db/schema.sql: escalations, incidents.routing_status`
- `api/openapi.yaml: /api/escalations*, Escalation*`

## Зависимости
- Зависит от: [T-061](T-061-uzel-decide-sla-marshrutizaciya-prioritet-politi.md), [T-062](T-062-uzel-act-kommunikacii-klientu-i-komandam.md), [T-076](T-076-politiki-hitl-policies-py-i-testy.md), [T-207](T-207-edinaya-shema-soobscheniya-i-normalizator-ingest.md), [T-212](T-212-problem-summary-problem-severity-suggested-team.md)
- Блокирует: [T-214](T-214-tiketnica-v-tickets-get-api-tickets-vkladka-tike.md), [T-220](T-220-scenarii-10-transkript-roznichnogo-dialoga-i-11.md)

## Что сделать
1. app/agent/tools/router_tools.py: четыре фасада; route_to_department → create_incident(+дедупликация → linked=true) + routing_status=routed; notify_customer → notify_client без шаблона с проверками формулировок; escalate_to_manager → INSERT escalations + HITL-элемент типа escalation + notify_team + routing_status=escalated; request_clarification → request_data + schedule_followup + routing_status=clarification. Каждый фасад логирует tool_call с wraps=[…].
2. Порядок функций в списке tools для модели: роутер-инструменты первыми; системный промпт decide v1.1 объясняет, когда какой.
3. decision.router_action обязателен; policy_checks: несогласованность router_action с фактическими вызовами → ошибка узла и повтор (1 раз), затем HITL.
4. Политика эскалации (policies.py): churn_threat при negativity ≥ 80; repeat при sentiment=negative; severity=critical; ≥ 3 обращений за 7 дней (флаг repeat_contact_7d). Уточнение: confidence < 0,6 или нет обязательных сущностей; второй подряд вопрос запрещён.
5. API эскалаций: список/деталь/ручная/ack; события escalation.*; WS-топик escalations; вкладка HITL получает фильтр «Эскалации» (T-214).
6. Тесты: 6 кейсов политики, фасады → вложенные вызовы, согласованность router_action.

## Критерии приёмки
- [ ] Сценарий 11: request_clarification → route_to_department(team_debit, 2, …) → escalate_to_manager(critical); эскалация в очереди руководителя CX.
- [ ] Для каждого решения router_action согласован с tool_calls (тест на 50 кассетных прогонах).
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/unit/test_router_tools.py backend/tests/unit/test_escalation_policy.py backend/tests/integration/test_escalations_api.py
```

## Отчёт субагента
Дополнение (ветка `feat/b13-tickets-escalations`): REST-часть эскалаций — `GET/POST /api/escalations`, `GET /api/escalations/{id}`, `POST /api/escalations/{id}/ack`; события `escalations` через pg_notify; ручная эскалация оператором (`created_by = human`) и из действий инцидента (`action = escalate`).
