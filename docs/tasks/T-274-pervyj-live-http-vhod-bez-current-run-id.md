# T-274 — Первый live HTTP-вход без current_run_id

| Поле | Значение |
|---|---|
| Эпик | E18 Приём транскриптов, роутер-инструменты, «красные фразы», зоны карты [ДТЗ] |
| Субагент | `SA-Agent` (агент LangGraph) |
| Оценка | S (≤ 0,5 дня) |
| Волна | 9 |
| Слой | `L3` Агент и контуры (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | нет — можно отложить |
| Статус | `done` |

## Цель
GitHub #105: согласованная точечная интеграция ensure_live_run в run_context.

## Разделы ТЗ (docs/TZ.md)
§4.7, §21.2

## Контракты


## Зависимости
- Зависит от: [T-180](T-180-rasshirenie-zapuskov-avtosozdanie-run-kind-live.md), [T-273](T-273-sintetika-tolko-po-yavnomu-zapusku.md)
- Блокирует: —

## Что сделать
1. Создать live только по явному входу и только при NULL, поддержать dict_row.
2. Синхронизировать память Simulator без запуска часов, проверить конкуренцию и shutdown.

## Критерии приёмки
- [x] Три первых запроса создают один live, агент обрабатывает реальный вход при running=false.
- [x] Baseline/free не заменяются; shutdown сохраняет созданный указатель.
- [x] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
make lint && make test
test_synthetic_ingest.py и test_live_run.py
```

## Отчёт субагента
Ветка `codex/idle-generation-csi-repair`, 30.10.2026. Cross-layer согласован. Контракты не менялись.
Полный make lint && make test: unit 588, integration 137, scenarios 22 passed;
compliance отдельно 31 passed. Frontend 132 passed, обе сборки. Подробности —
[доказательства и SQL](../benchmarks/idle-generation/README.md).

Отдельное согласование пользователя получено в чате. run_context использует ensure_live_run;
конкурентные HTTP-запросы, работа агента при false, память/shutdown и baseline/free проверены регрессиями.
