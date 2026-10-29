# T-065 — Трассировка запусков и стриминг токенов

| Поле | Значение |
|---|---|
| Эпик | E5 Агент LangGraph |
| Субагент | `SA-Agent` (агент LangGraph) |
| Оценка | M (1–2 дня) |
| Волна | 3 |
| Слой | `L3` Агент и контуры (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `done` |

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
- Блокирует: [T-067](T-067-zhyuri-rezhim-ruchnoj-vvod-signala-i-sravnenie-s.md), [T-106](T-106-zhivaya-trassirovka-agenta.md), [T-163](T-163-llm-dvojniki-podsvechennyh-klientov.md), [T-201](T-201-panel-log-debug-kak-obschij-komponent-demo-ekran.md), [T-227](T-227-put-obrascheniya-rezhimy-sledit-povtor-veduschij.md)

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
- **Ветка:** `feat/T-065-tracing-token-stream` (от `main`)
- **Сделано:** `Deps.begin_step` → NOTIFY `agent/step_started`; `record_step` шлёт `agent_tokens/delta` по `response_raw`, `agent/step_finished`, копит `cost`, ужимает текстовые поля шага в бюджет 200 КБ; `run_graph` вызывает `begin_step` + commit до узла; `process_signal` пишет `llm_profile_id` и подставляет цены из `llm_profiles`; `_finish` — `cost_estimate`; GET `/api/agent/runs` — 422 на нечисловой `cursor`; тесты `tests/unit/test_tracing.py`, `tests/integration/test_tracing.py`.
- **Доработка 1/2 (ревью):** дельты строятся из ужатого `response_raw` после `_fit_step_texts`; JSON `output`/`tool_calls` не режутся посередине — при нехватке бюджета `{}`/`[]`; `resume_after_human` восстанавливает `text_bytes_used` из БД; доп. unit/integration тесты.
- **Доработка 2/2:** patch `record_step` в integration-тесте resume только после HITL-паузы; в API-тесте сценарий QR-комиссии (mass), как в `test_agent.py`, для стабильного `outcome=completed`.
- **Отклонения:** нет
- **Контракты:** не менялись (`contracts/` без правок)

Доработка 29.10.2026: input шага normalize содержит попытки provider/model/ok/ms/error и fallback_reason, reasoning объясняет переход на резерв. Успешный main отражается фактической моделью и source=live. Токены и стоимость невалидных оплаченных попыток добавляются к общему usage, а не теряются при смене модели. API/схема БД не менялись.
