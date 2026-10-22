# T-180 — Расширение запусков: автосоздание run kind=live и независимость живых контуров от сим-часов

| Поле | Значение |
|---|---|
| Эпик | E15 Внешние площадки и автономный возврат [BRD] |
| Субагент | `SA-Teams` (симулятор, команды, SLA) |
| Оценка | S (≤ 0,5 дня) |
| Волна | 2 |
| Слой | `L2` Симулятор и данные (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `todo` |

## Цель
Живые контуры (/feed, /compliance, «Надиктовать») работают при паузе и без запуска (ТЗ 4.7).

## Разделы ТЗ (docs/TZ.md)
§4.6, §4.7

## Контракты
- `db/schema.sql: sim_runs.kind = live`
- `events/common.schema.json: sim_run_kind`

## Зависимости
- Зависит от: [T-040](T-040-servis-zapuskov-emulyacii-sim-runs-run-id-rezhim.md)
- Блокирует: [T-183](T-183-audiosessii-repliki-i-tri-rezhima-razdeleniya-sp.md)

## Что сделать
1. app/sim/runs.py: ensure_live_run() — если current_run_id IS NULL, создать sim_runs(kind='live', label='живой показ') и выставить текущим; вызывается приёмником отзывов, сессиями аудио и голосовым вводом.
2. События живых контуров получают sim_time из SimClock даже на паузе (метка), latency считается по real time.
3. Вкладка «Запуски» (T-094): метка «живой показ» для kind=live.

## Критерии приёмки
- [ ] При остановленном симуляторе POST /api/public/reviews создаёт run live и обрабатывается агентом.
- [ ] Изоляция по run_id сохраняется (тест T-146 расширен).
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/integration/test_live_run.py
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
