# T-164 — Уход клиента: churn_events, инцидент account_closure, закрытие продуктов

| Поле | Значение |
|---|---|
| Эпик | E14 Поведение клиентов и калькулятор «Факт» |
| Субагент | `SA-Behavior` (поведение клиентов) |
| Оценка | M (1–2 дня) |
| Волна | 3 |
| Слой | `L2` Симулятор и данные (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `todo` |

## Цель
Уход — измеримое событие и внутренний инцидент для разбора.

## Разделы ТЗ (docs/TZ.md)
§4.5, §8.1, §14.5

## Контракты
- `events/behavior/client_event.schema.json (client.account_closure)`
- `db/schema.sql: churn_events, incidents (account_closure)`

## Зависимости
- Зависит от: [T-161](T-161-parametricheskaya-model-sostoyanij-klienta.md), [T-058](T-058-instrumenty-zapisi-i-pobochnyh-effektov.md), [T-131](T-131-raschet-ekonomiki-dcltv-po-incidentu.md)
- Блокирует: [T-166](T-166-vkladka-kalkulyatora-fakt-po-simulyacii-api-ui-e.md), [T-167](T-167-statisticheskie-testy-modeli-povedeniya.md)

## Что сделать
1. При переходе churned: churn_events (причина, связанные инциденты, что предлагали, дни после инцидента), создание инцидента account_closure через create_incident (team_cx, medium, критичность по сегменту, HITL для vip/ultra_vip, без ответа клиенту), clients.is_active=false, закрытие client_products, realized_loss через compute_economics, outcome_class связанных инцидентов → churned.
2. Артефакт closure_review (шаблон/fast-модель): «почему не удержали».

## Критерии приёмки
- [ ] Сценарий 7: premium demanding_rational уходит после срыва SLA; инцидент account_closure с заполненными полями появляется у CX; строка в калькуляторе «Факт».
- [ ] Повторный уход одного клиента невозможен.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/unit/test_churn.py
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
