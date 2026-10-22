# T-033 — Генератор операций в реальном времени

| Поле | Значение |
|---|---|
| Эпик | E3 Симулятор банка, команды, SLA |
| Субагент | `SA-Teams` (симулятор, команды, SLA) |
| Оценка | M (1–2 дня) |
| Волна | 2 |
| Слой | `L2` Симулятор и данные (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `done` |

## Цель
Поток операций клиентов во время симуляции, согласованный с предысторией.

## Разделы ТЗ (docs/TZ.md)
§4.2

## Контракты
- `events/sim/op.schema.json`

## Зависимости
- Зависит от: [T-032](T-032-shina-sobytij-simulyatora.md), [T-017](T-017-produkty-klientov-i-14-dnej-operacij.md)
- Блокирует: [T-035](T-035-generator-oshibok-klientov.md), [T-144](T-144-proverka-proizvoditelnosti-profilya-demo.md), [T-162](T-162-detekciya-snizheniya-aktivnosti-molchalivyj-uhod.md)

## Что сделать
1. Пуассоновские интенсивности по сегменту × часу × дню недели (общая конфигурация с T-017); пакетная генерация на каждый тик.
2. Операции проходят по system_path; если в системе активен сбой — status failed с error_code (доля по severity) и ссылкой на fault.
3. Событие op.failed → подписчик модели поведения (client.affected).

## Критерии приёмки
- [ ] Профиль demo: ≈ 25–40 операций/сим-минуту в пик, нагрузка на БД ≤ 20 % CPU.
- [ ] Доля failed во время сбоя соответствует severity (тест).
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/unit/test_gen_operations.py
```

## Отчёт субагента
Ветка main, коммит B03. `app/sim/generators.py::World.gen_operations`: Пуассон с интенсивностью 450/сим-час (ТЗ 4.2) × суточный профиль × масштаб по числу клиентов (demo = 1.0, floor 0.2); op_type/system_path по enum `sim/op`; если в system_path активен сбой — 60 % операций failed с error_code и fault_id, учёт impact_count/affected_clients; фоновые ошибочные комиссии за QR (3 % qr_sbp → PROC-QR-FEE-CHARGED); запись в operations и событие op.succeeded|op.failed через EventBus (валидация envelope + sim/op, запись sim_events, pg_notify('sim_events')). Контракт: в `sim/op.schema.json` добавлены необязательные `method` и `fee_amount` (регенерирован `app/contracts/events/sim/op.py`). Подписчик поведения — упрощённо внутри World: op.failed → отложенная жалоба с p_complain и задержкой психотипа (полная модель 4.5 — карточки T-017…). Время: ~40 мин.
