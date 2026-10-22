# T-214 — Тикетница: v_tickets, GET /api/tickets, вкладка «Тикеты» и фильтр «Эскалации» в HITL, экспорт цепочки решений decision-chain

| Поле | Значение |
|---|---|
| Эпик | E18 Приём транскриптов, роутер-инструменты, «красные фразы», зоны карты [ДТЗ] |
| Субагент | `SA-UI-Workspace` (рабочее место CX) |
| Оценка | M (1–2 дня) |
| Волна | 4 |
| Слой | `L4` Фронт (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `todo` |

## Цель
Внешний контракт ДТЗ «тикетница» и «лог цепочки решений» без второго хранилища (ДТЗ FR-3.2, FR-3.5; ТЗ 9.7, 12.5, решение 20.6 п. 18, критерии 30–31).

## Разделы ТЗ (docs/TZ.md)
§9.7, §12.2, §12.5, §19

## Контракты
- `db/schema.sql: v_tickets`
- `api/openapi.yaml: /api/tickets*, GET /api/agent/runs/{id}/decision-chain, Ticket, TicketDetail`
- `events/agent/decision_chain.schema.json`

## Зависимости
- Зависит от: [T-213](T-213-router-instrumenty-route-to-department-notify-cu.md), [T-089](T-089-doska-i-tablica-incidentov-s-indikatorami-sla.md), [T-106](T-106-zhivaya-trassirovka-agenta.md)
- Блокирует: [T-220](T-220-scenarii-10-transkript-roznichnogo-dialoga-i-11.md)

## Что сделать
1. Backend: GET /api/tickets (v_tickets + фильтры), GET /api/tickets/{ticket_id} (инцидент + эскалации + цепочка); GET /api/agent/runs/{id}/decision-chain в JSON и Markdown (why_ru из rationale_ru узлов и human_recommendation; маскировка ПДн в args).
2. UI: переключатель терминов «Инциденты / Тикеты» на доске (меняет подписи колонок и статусы на open/in_progress/resolved/closed/rejected); в карточке тикета кнопка «Почему так решили» → цепочка; кнопка «Скопировать как Markdown».
3. Вкладка HITL: фильтр «Эскалации» (элементы типа escalation), действия acknowledged/resolved/dismissed с резолюцией; счётчик открытых эскалаций в шапке.
4. Лента инцидентов (T-087/T-089): поля problem_summary.problem, routing_status, channel, sentiment в элементе списка.
5. e2e: тикет сценария 11 виден в «Тикетах», цепочка экспортируется.

## Критерии приёмки
- [ ] GET /api/tickets возвращает тикет сценария 11 с escalated=true и routing_status=escalated.
- [ ] Markdown цепочки содержит все четыре роутер-инструмента с «почему».
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/integration/test_tickets_api.py
npx playwright test e2e/tickets-chain.spec.ts
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
