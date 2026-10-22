# T-175 — Инструменты refund_fee, find_affected_clients, get_account_balance и массовый возврат через HITL

| Поле | Значение |
|---|---|
| Эпик | E15 Внешние площадки и автономный возврат [BRD] |
| Субагент | `SA-Agent` (агент LangGraph) |
| Оценка | M (1–2 дня) |
| Волна | 3 |
| Слой | `L3` Агент и контуры (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `todo` |

## Цель
Единственный путь движения денег для агента — инструмент с проверкой правила, лимита и идемпотентности; массовые последствия — отдельный инцидент с HITL (ТЗ 9.2–9.3, 21.4 п. 6).

## Разделы ТЗ (docs/TZ.md)
§9.2, §9.3, §21.4

## Контракты
- `events/agent/tool_call.schema.json`
- `events/sim/abs.schema.json`
- `api/openapi.yaml: POST /api/abs/refunds`

## Зависимости
- Зависит от: [T-171](T-171-mock-abs-scheta-tarify-provodki-sid-i-invariant.md), [T-172](T-172-rules-engine-business-rules-dsl-uslovij-uzel-che.md), [T-058](T-058-instrumenty-zapisi-i-pobochnyh-effektov.md), [T-077](T-077-uzel-wait-human-ochered-hitl-i-vozvrat-resheniya.md)
- Блокирует: [T-179](T-179-scenarij-8-komissiya-za-qr-oplatu-i-publichnyj-o.md)

## Что сделать
1. refund_fee(operation_id, amount_rub, rule_id, reason): проверяет rule_evaluations.matched для операции, лимит из политик, отсутствие refund для той же fee-проводки, пишет ledger refund + abs.refund_posted; ошибка → ToolError без побочных эффектов.
2. find_affected_clients(error_code, window) → список клиентов/операций с той же ошибкой; при ≥ mass_refund_threshold агент создаёт инцидент tech_fault (mass_impact) в team_processing и request_human_decision «массовый возврат N × сумма».
3. После решения человека — пакетный возврат через POST /api/abs/refunds с прогрессом в WebSocket abs и проактивные уведомления пострадавшим (ветка T-039).
4. get_account_balance(client_id) для verify_service_delivered на быстром пути.

## Критерии приёмки
- [ ] refund_fee отказывает без matched-правила и при превышении лимита (тесты).
- [ ] Массовый сценарий: 37 пострадавших → один инцидент tech_fault, HITL, после подтверждения 37 проводок refund и 37 уведомлений.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/unit/test_tools_refund.py backend/tests/integration/test_mass_refund.py
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
