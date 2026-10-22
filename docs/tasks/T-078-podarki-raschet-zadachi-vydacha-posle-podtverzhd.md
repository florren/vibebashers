# T-078 — Подарки: расчёт, задачи, выдача после подтверждения услуги

| Поле | Значение |
|---|---|
| Эпик | E6 HITL и подарки |
| Субагент | `SA-Agent` (агент LangGraph) |
| Оценка | M (1–2 дня) |
| Волна | 4 |
| Слой | `L3` Агент и контуры (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `todo` |

## Цель
Петля замыкается подарком по правилам справочника; привилегии — через человека.

## Разделы ТЗ (docs/TZ.md)
§8.5, §6 шаг 5, §20.1 п. 9

## Контракты
- `db/schema.sql: gift_catalog, tasks`
- `api/openapi.yaml: tasks/*`

## Зависимости
- Зависит от: [T-058](T-058-instrumenty-zapisi-i-pobochnyh-effektov.md), [T-061](T-061-uzel-decide-sla-marshrutizaciya-prioritet-politi.md), [T-015](T-015-shablony-uvedomlenij-spravochnik-podarkov-stavki.md), [T-077](T-077-uzel-wait-human-ochered-hitl-i-vozvrat-resheniya.md)
- Блокирует: [T-063](T-063-uzly-followup-monitor-verify-close-gift-i-otlozh.md), [T-080](T-080-ui-zadach-i-podarkov.md)

## Что сделать
1. app/agent/gifts.py: выбор подарка по сегменту/критичности/повтору/психотипу (status_oriented → привилегия, bonus_hunter → баллы по верхней границе в cap), requires_hitl для партнёрских привилегий и ultra_vip.
2. Задача kind=gift создаётся при resolved, выдаётся (done) после verify и одобрения; уведомление gift_offer; outcome_class → closed_in_sla_with_gift.
3. API задач: approve/change/reject/done.

## Критерии приёмки
- [ ] VIP в сценарии 1 получает баллы + предложение бизнес-зала только после одобрения.
- [ ] Клиент mass получает баллы автоматически без HITL.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/unit/test_gifts.py
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
