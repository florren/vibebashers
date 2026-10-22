# T-032 — Шина событий симулятора

| Поле | Значение |
|---|---|
| Эпик | E3 Симулятор банка, команды, SLA |
| Субагент | `SA-Teams` (симулятор, команды, SLA) |
| Оценка | S (≤ 0,5 дня) |
| Волна | 2 |
| Слой | `L2` Симулятор и данные (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `todo` |

## Цель
Все события проходят через одну точку: валидация, запись, NOTIFY, корреляция.

## Разделы ТЗ (docs/TZ.md)
§4.2, §5.1

## Контракты
- `events/envelope.schema.json`
- `events/sim/*`
- `db/schema.sql: sim_events`

## Зависимости
- Зависит от: [T-031](T-031-simclock-sim-state-i-upravlenie-simulyaciej.md), [T-006](T-006-sync-contracts-generaciya-enums-pydantic-shem-ts.md)
- Блокирует: [T-033](T-033-generator-operacij-v-realnom-vremeni.md), [T-034](T-034-generator-sboev-i-vosstanovlenij.md), [T-035](T-035-generator-oshibok-klientov.md), [T-036](T-036-emulyator-komand-i-cifrovoj-sled-incidenta.md), [T-037](T-037-sla-dvizhok.md), [T-040](T-040-servis-zapuskov-emulyacii-sim-runs-run-id-rezhim.md), [T-056](T-056-agentstate-graf-langgraph-checkpointer-zapusk-po.md), [T-161](T-161-parametricheskaya-model-sostoyanij-klienta.md), [T-176](T-176-priemnik-otzyvov-external-posts-replies-instrume.md)

## Что сделать
1. app/sim/bus.py: emit(event_type, payload, sim_time, correlation_id, causation_id, scenario_id) → валидация по схеме (всегда в dev/test, 10 % в prod), INSERT sim_events, pg_notify('sim_events').
2. Подписчики внутри процесса (агент, SLA, поведение) регистрируются по префиксу типа.
3. API /api/sim/events с фильтрами и курсором.

## Критерии приёмки
- [ ] Каждое событие несёт run_id текущего запуска (envelope.schema.json, required); публикация без run_id отклоняется валидатором.
- [ ] Невалидное событие в dev бросает исключение с путём ошибки.
- [ ] Корреляция: сигнал, порождённый сбоем, несёт correlation_id сбоя.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/unit/test_bus.py
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
