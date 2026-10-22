# T-042 — Итоговые метрики запуска (summary) и экспорт

| Поле | Значение |
|---|---|
| Эпик | E3 Симулятор банка, команды, SLA |
| Субагент | `SA-Economics` (экономика и калькулятор) |
| Оценка | S (≤ 0,5 дня) |
| Волна | 3 |
| Слой | `L2` Симулятор и данные (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `todo` |

## Цель
При завершении запуска фиксируется полный набор показателей 14.1/14.4/14.5 и расход токенов — основа истории и сравнения запусков.

## Разделы ТЗ (docs/TZ.md)
§4.6, §14.1, §14.4, §14.5

## Контракты
- `api/openapi.yaml: SimRun.summary, sim/runs/{id}/export, sim/runs/compare`
- `db/schema.sql: sim_runs.summary, v_run_counters, v_incident_outcomes, v_retention_by_outcome`

## Зависимости
- Зависит от: [T-040](T-040-servis-zapuskov-emulyacii-sim-runs-run-id-rezhim.md), [T-132](T-132-api-svodnoj-ekonomiki-i-metrik-dashborda.md)
- Блокирует: [T-094](T-094-vkladka-zapuski-istoriya-sravnenie-sbros-k-basel.md), [T-146](T-146-testy-izolyacii-zapuskov-i-vozobnovleniya.md)

## Что сделать
1. app/sim/run_summary.py: build_summary(run_id) собирает DashboardMetrics(window=run), EconomicsSummary, факт удержания по исходам/психотипам, токены и стоимость по llm_profiles, длительность реальную и сим, число HITL/подарков/уходов; схема summary версионирована (summary_version).
2. Экспорт JSON (summary + агрегаты по часам/продуктам/командам) и CSV событий; compare: разность по числовым ключам summary.
3. Пересчёт summary для прошлых запусков командой make run-summary ID=…

## Критерии приёмки
- [ ] summary заполняется при stop/complete и совпадает с ответами metrics API по run_id (тест).
- [ ] Экспорт JSON открывается и содержит все разделы; CSV ≥ 1 строка на событие.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/unit/test_run_summary.py
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
