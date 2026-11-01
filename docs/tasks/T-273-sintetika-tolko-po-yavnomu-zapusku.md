# T-273 — Синтетика только по явному запуску

| Поле | Значение |
|---|---|
| Эпик | E18 Приём транскриптов, роутер-инструменты, «красные фразы», зоны карты [ДТЗ] |
| Субагент | `SA-Agent` (агент LangGraph) |
| Оценка | M (1–2 дня) |
| Волна | 9 |
| Слой | `L3` Агент и контуры (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | нет — можно отложить |
| Статус | `done` |

## Цель
GitHub #104: доказать источник фоновой генерации и исключить её в idle/pause/restart.

## Разделы ТЗ (docs/TZ.md)
§3.7, §4.6, §4.7

## Контракты


## Зависимости
- Зависит от: [T-207](T-207-edinaya-shema-soobscheniya-i-normalizator-ingest.md)
- Блокирует: [T-274](T-274-pervyj-live-http-vhod-bez-current-run-id.md)

## Что сделать
1. Чистые стенды до/после: SQL, 120 секунд idle/pause/restart.
2. Явный mock без real-time генерации, run_id и corpus; реальный вход сохранён.
3. Recovery и callbacks исключают legacy fake, настоящие обращения восстанавливаются.

## Критерии приёмки
- [x] Enabled mock не растёт в idle/pause и после restart; start/resume штатны.
- [x] Fixed seed воспроизводим; URL не подменяется синтетикой; live не блокируется.
- [x] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
make lint && make test
docs/benchmarks/idle-generation/observe.py
```

## Отчёт субагента
Ветка `codex/idle-generation-csi-repair`, 30.10.2026. Cross-layer согласован. Контракты не менялись.
Полный make lint && make test: unit 588, integration 137, scenarios 22 passed;
compliance отдельно 31 passed. Frontend 132 passed, обе сборки. Подробности —
[доказательства и SQL](../benchmarks/idle-generation/README.md).

Реализация и SQL/замеры: ADR-0019, docs/benchmarks/idle-generation/README.md.
До: +100 сигналов/120 секунд idle, 50 polling agent_runs после restart.
После при enabled=true: нулевой рост в idle/pause/restart; start/resume штатны.
