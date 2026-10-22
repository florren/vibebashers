# T-065 — Трассировка запусков и стриминг токенов

| Поле | Значение |
|---|---|
| Эпик | E5 Агент LangGraph |
| Субагент | `SA-Agent` (агент LangGraph) |
| Оценка | M (1–2 дня) |
| Волна | 3 |
| Слой | `L3` Агент и контуры (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `todo` |

## Цель
Каждый шаг агента записан и транслируется в реальном времени — основа экрана «Под капотом».

## Разделы ТЗ (docs/TZ.md)
§12.2 экран 4, §12.3, §12.5

## Контракты
- `db/schema.sql: agent_runs, agent_steps`
- `events/ws/message.schema.json ($defs agent_step, agent_tokens_delta)`
- `api/openapi.yaml: agent/runs*`

## Зависимости
- Зависит от: [T-056](T-056-agentstate-graf-langgraph-checkpointer-zapusk-po.md), [T-008](T-008-realtime-listen-notify-websocket-hab.md)
- Блокирует: [T-067](T-067-zhyuri-rezhim-ruchnoj-vvod-signala-i-sravnenie-s.md), [T-106](T-106-zhivaya-trassirovka-agenta.md), [T-163](T-163-llm-dvojniki-podsvechennyh-klientov.md), [T-201](T-201-panel-log-debug-kak-obschij-komponent-demo-ekran.md)

## Что сделать
1. Обёртка узлов: запись agent_steps (вход/выход/промпт/сырой ответ/reasoning/tool_calls/токены/латентность), публикация agent/step_started|step_finished, agent_tokens/delta при стриминге.
2. Итоги в agent_runs (outcome, needed_human, токены, cost_estimate по ценам профиля).
3. API списка/деталей запусков с курсором; фильтры kind/signal/outcome.

## Критерии приёмки
- [ ] Для запуска на Ultra видны все шаги с промптами и ответами; дельты токенов приходят ≤ 300 мс после модели.
- [ ] Объём agent_steps на один запуск ≤ 200 КБ.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/integration/test_tracing.py
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
