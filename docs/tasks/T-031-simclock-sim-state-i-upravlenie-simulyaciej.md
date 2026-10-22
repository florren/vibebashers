# T-031 — SimClock, sim_state и управление симуляцией

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
Единое симуляционное время с рабочим календарём и пресетами скорости.

## Разделы ТЗ (docs/TZ.md)
§4.1, §12.2 экран 2 (панель управления)

## Контракты
- `api/openapi.yaml: sim/state, sim/control`
- `db/schema.sql: sim_state`

## Зависимости
- Зависит от: [T-004](T-004-karkas-fastapi-konfig-logirovanie-oshibki-health.md), [T-005](T-005-primenenie-schema-sql-sqlalchemy-modeli-sessii.md), [T-008](T-008-realtime-listen-notify-websocket-hab.md)
- Блокирует: [T-032](T-032-shina-sobytij-simulyatora.md), [T-037](T-037-sla-dvizhok.md), [T-040](T-040-servis-zapuskov-emulyacii-sim-runs-run-id-rezhim.md), [T-041](T-041-preryvanie-i-vozobnovlenie-emulyacii-vosstanovle.md), [T-086](T-086-layout-rabochego-mesta-cx-shapka-sim-chasy-panel.md), [T-161](T-161-parametricheskaya-model-sostoyanij-klienta.md)

## Что сделать
1. app/sim/clock.py: tick-цикл asyncio, speed (сим-сек/реал-сек), пресеты demo_5min (12 сим-часов за 5 мин), day_12min, realtime; фазы morning/day/evening/night; рабочие дни пн–пт 09:00–18:00; функции add_working_days/hours для SLA.
2. Персистентность в sim_state, восстановление после рестарта; jump_to только вперёд с «быстрым прогоном» генераторов.
3. API /api/sim/state, /api/sim/control (start/pause/resume/stop/step/reset_day/set_speed/set_preset/jump_to) и публикация sim/tick в WS каждую сим-минуту (≤ 4 сообщения/с). Семантика статусов запуска — ТЗ 4.6; сами запуски (sim_runs) реализует T-040, здесь — хуки on_start/on_pause/on_resume/on_stop и поле sim_state.current_run_id.
4. Единый rng.py (seeded Generator) с сериализацией состояния в sim_state.rng_state на каждом тике (для возобновления); сид в sim_state.
5. sim_state.last_tick_at обновляется каждый тик; при старте приложения, если running=true и last_tick_at устарел, статус текущего запуска → interrupted (T-041).

## Критерии приёмки
- [ ] Два запуска с одним сидом и mock-LLM дают идентичные sim_events (тест детерминизма).
- [ ] Пауза останавливает все генераторы; шаг двигает ровно на step_minutes.
- [ ] Stop завершает запуск, Resume после pause продолжает с того же sim_time без пропусков и дублей тиков.
- [ ] Циркадная тема получает фазу из sim/tick.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/unit/test_clock.py backend/tests/integration/test_determinism.py
```

## Отчёт субагента
Ветка main, коммит B03. `app/sim/clock.py` (SimClock, пресеты demo_5min=144 сим-с/с, day_12min=60, realtime=1; фазы morning/day/evening/night; рабочие дни пн–пт 09:00–18:00; add_working_days/add_working_hours), `app/sim/rng.py` (SimRng: Пуассон, взвешенный выбор, dump/load состояния → sim_state.rng_state на каждом тике), `app/sim/engine.py` (Simulator: tick 0,5 с, блоки ≤ 60 сим-мин, персистентность sim_state, восстановление после рестарта и перевод running→interrupted при устаревшем last_tick_at; control: start/pause/resume/stop/step/reset_day/set_speed/set_preset/jump_to только вперёд с быстрым прогоном; публикация sim.tick в WS раз в сим-минуту), `app/api/sim.py`: реальные GET /api/sim/state, POST /api/sim/control (pydantic-валидация тела по openapi), GET /api/sim/events (фильтры run_id/type/since_sim, курсор), GET /api/sim/runs, /runs/current, /runs/{id}, POST /runs/{id}/stop|resume. Инициализация в lifespan (`app.state.sim`), в APP_ENV=test не стартует (503). Отклонение: sim.tick публикуется напрямую в hub (не через NOTIFY); события op.* идут в топик sim без агрегации (может превышать 4 сообщения/с на demo_5min). Тесты: `tests/integration/test_sim.py`. Время: ~70 мин.
