# T-089 — Доска и таблица инцидентов с индикаторами SLA

| Поле | Значение |
|---|---|
| Эпик | E7 Рабочее место CX |
| Субагент | `SA-UI-Workspace` (рабочее место CX) |
| Оценка | M (1–2 дня) |
| Волна | 3 |
| Слой | `L4` Фронт (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `todo` |

## Цель
Канбан по статусам и табличный вид с SLA-прогрессом, фильтрами и сортировкой.

## Разделы ТЗ (docs/TZ.md)
§12.2 экран 2 (инциденты), §8.2, §8.3

## Контракты
- `api/openapi.yaml: incidents (list)`
- `events/ws/message.schema.json (incidents)`

## Зависимости
- Зависит от: [T-086](T-086-layout-rabochego-mesta-cx-shapka-sim-chasy-panel.md), [T-058](T-058-instrumenty-zapisi-i-pobochnyh-effektov.md), [T-037](T-037-sla-dvizhok.md)
- Блокирует: [T-090](T-090-kartochka-incidenta.md), [T-214](T-214-tiketnica-v-tickets-get-api-tickets-vkladka-tike.md)

## Что сделать
1. Канбан по группам статусов; карточка-плитка: public_id, заголовок, продукт/система, команда, критичность/сложность, SLA-бар с остатком, флаги, mass_impact, следующий отчёт.
2. Таблица с сортировкой по priority/sla_due; подсветка warning/breached; счётчики by_status.
3. Переход в карточку (T-090).

## Критерии приёмки
- [ ] Смена статуса в БД отражается на доске ≤ 1 с.
- [ ] Просроченные выделены и первыми в сортировке.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
npx playwright test e2e/incidents.spec.ts
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
