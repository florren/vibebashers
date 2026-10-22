# T-035 — Генератор ошибок клиентов

| Поле | Значение |
|---|---|
| Эпик | E3 Симулятор банка, команды, SLA |
| Субагент | `SA-Teams` (симулятор, команды, SLA) |
| Оценка | S (≤ 0,5 дня) |
| Волна | 3 |
| Слой | `L2` Симулятор и данные (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `done` |

## Цель
Сигналы, где виноват не банк: истёкшая акция, неверные реквизиты, непонятая комиссия.

## Разделы ТЗ (docs/TZ.md)
§4.2, §7

## Контракты
- `events/sim/client_error.schema.json`

## Зависимости
- Зависит от: [T-032](T-032-shina-sobytij-simulyatora.md), [T-033](T-033-generator-operacij-v-realnom-vremeni.md)
- Блокирует: —

## Что сделать
1. client_error.* события по интенсивности 4.2; привязка к операции и продукту; подписчик поведения создаёт сигнал типа client_error с вероятностью психотипа (novice выше).

## Критерии приёмки
- [ ] Агент классифицирует такие сигналы как client_error ≥ 85 % на mock и ≥ 90 % на Ultra (проверка на lite).
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/unit/test_gen_client_errors.py
```

## Отчёт субагента
Ветка main, коммит B03. `World.gen_client_errors`: интенсивность 30/сим-час × масштаб, виды wrong_details/fee_misread/promo_expired/missed_payment/app_misuse с привязкой к продукту; событие client_error.<kind> по `sim/client_error`; жалоба типа client_error с вероятностью p_complain × 1.5 для novice (× 0.6 для остальных) через общий механизм отложенных сигналов → signals (origin sim, sentiment из gold) + signal.received + NOTIFY signals. Время: ~15 мин.
