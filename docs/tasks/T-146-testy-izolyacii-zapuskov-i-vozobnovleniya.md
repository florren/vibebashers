# T-146 — Тесты изоляции запусков и возобновления

| Поле | Значение |
|---|---|
| Эпик | E11 Сценарии и тесты |
| Субагент | `SA-QA` (тесты и CI) |
| Оценка | M (1–2 дня) |
| Волна | 5 |
| Слой | `L5` Качество (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | нет — можно отложить |
| Статус | `todo` |

## Цель
Автоматически доказать критерии приёмки 16 и 17: запуски не загрязняют друг друга, прерывание восстанавливается.

## Разделы ТЗ (docs/TZ.md)
§4.6, §19 п. 16–17

## Контракты
- `api/openapi.yaml: sim/runs*, scenarios/{id}/run`
- `events/envelope.schema.json (run_id)`

## Зависимости
- Зависит от: [T-142](T-142-avtotesty-7-demo-scenariev.md), [T-040](T-040-servis-zapuskov-emulyacii-sim-runs-run-id-rezhim.md), [T-041](T-041-preryvanie-i-vozobnovlenie-emulyacii-vosstanovle.md), [T-042](T-042-itogovye-metriki-zapuska-summary-i-eksport.md)
- Блокирует: —

## Что сделать
1. backend/tests/scenarios/test_run_isolation.py: сценарий 1 дважды в режиме counters → счётчики второго не включают первый; в режиме baseline с одним сидом на mock → идентичные sim_events (без id/real_time) и summary.
2. Тест «нет сирот»: после любого сценария нет строк с run_id IS NULL в таблицах данных (список таблиц — из information_schema по наличию колонки run_id).
3. backend/tests/integration/test_interrupt_resume.py: убить процесс тиков посреди обработки сигнала (fixture с подпроцессом), перезапустить приложение, resume → проверки из T-041; отдельный тест на 409 для stopped.
4. e2e: runs.spec.ts — новый запуск, стоп, возобновление, сравнение, экспорт (Playwright).

## Критерии приёмки
- [ ] Все тесты зелёные на mock в CI ≤ 6 мин.
- [ ] Отчёт о покрытии критериев 16–17 приложен к PR.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/scenarios/test_run_isolation.py backend/tests/integration/test_interrupt_resume.py
npx playwright test e2e/runs.spec.ts
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
