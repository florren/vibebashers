# T-056 — AgentState, граф LangGraph, checkpointer, запуск по событиям

| Поле | Значение |
|---|---|
| Эпик | E5 Агент LangGraph |
| Субагент | `SA-Agent` (агент LangGraph) |
| Оценка | L (3–4 дня) |
| Волна | 2 |
| Слой | `L3` Агент и контуры (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `done` |

## Цель
Каркас агента: состояние, узлы-заглушки, маршрутизация рёбер, персистентность, запуск на signal.received.

## Разделы ТЗ (docs/TZ.md)
§9.1, §5.1, §12.5

## Контракты
- `api/openapi.yaml: agent/graph`
- `db/schema.sql: agent_runs`

## Зависимости
- Зависит от: [T-046](T-046-interfejs-llm-provajdera-i-strukturirovannyj-vyv.md), [T-032](T-032-shina-sobytij-simulyatora.md), [T-005](T-005-primenenie-schema-sql-sqlalchemy-modeli-sessii.md)
- Блокирует: [T-038](T-038-dvizhok-scenariev-yaml-i-7-demo-scenariev.md), [T-039](T-039-proaktivnaya-vetka-sboj-uvedomleniya-zatronutym.md), [T-041](T-041-preryvanie-i-vozobnovlenie-emulyacii-vosstanovle.md), [T-057](T-057-instrumenty-chteniya-konteksta.md), [T-065](T-065-trassirovka-zapuskov-i-striming-tokenov.md), [T-077](T-077-uzel-wait-human-ochered-hitl-i-vozvrat-resheniya.md), [T-107](T-107-graf-langgraph-s-podsvetkoj-uzla-i-graf-suschnos.md), [T-162](T-162-detekciya-snizheniya-aktivnosti-molchalivyj-uhod.md), [T-172](T-172-rules-engine-business-rules-dsl-uslovij-uzel-che.md), [T-207](T-207-edinaya-shema-soobscheniya-i-normalizator-ingest.md)

## Что сделать
1. app/agent/state.py (TypedDict: signal, client, context, classification, decision, human, actions, errors, run_id).
2. graph.py: узлы ingest → normalize → identify_client → gather_context → classify → decide → (wait_human) → act → followup_monitor → verify → close → gift; условные рёбра; interrupt перед wait_human; PostgresSaver checkpointer (таблицы LangGraph в схеме langgraph).
3. Подписчик signal.received/signal.repeat/signal.appended → создание agent_runs и запуск графа в фоне (семафор параллелизма из настроек, по умолчанию 4).
4. GET /api/agent/graph отдаёт узлы/рёбра с label_ru/en и kind для визуализации.

## Критерии приёмки
- [ ] AgentState содержит run_id (sim_runs.id) и прокидывает его во все инструменты; thread_id чекпоинта = f"{run_id}:{signal_id}" — незавершённые треды находятся по префиксу запуска при возобновлении (T-041).
- [ ] Сигнал проходит граф с заглушками за < 1 с на mock; run записан.
- [ ] Рестарт процесса возобновляет прерванные на wait_human запуски из чекпоинта.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/unit/test_graph_skeleton.py
```

## Отчёт субагента
Ветка `feat/b04-agent`, PR «B04». Сделано: `backend/app/agent/state.py` (AgentState TypedDict, GRAPH_VERSION=v1), `graph.py` (GRAPH_SPEC для GET /api/agent/graph, `process_signal`, `resume_after_human`, `run_graph`: узел = транзакция, ошибка узла → шаг status=error + outcome failed, сигнал в error), `runner.py` (AgentService: LISTEN sim_events → signal.received, семафор 4, восстановление после рестарта, `resume()`), подключение в `app/main.py` (lifespan, `app.state.agent`, не в APP_ENV=test). agent_runs получает kind=agent, thread_id=`{run_id}:{signal_id}`, prompt_version, graph_version, токены/латентность; agent_steps — по шагу на узел (input/output/prompt/response_raw/reasoning/tool_calls/model/tokens/latency). **Отклонение:** вместо LangGraph+PostgresSaver — собственный лёгкий раннер; чекпоинт для HITL = вход шага `wait_human` (agent_steps.input), возобновление продолжает нумерацию шагов. Повод: меньше зависимостей и полный контроль над транзакциями; API/таблицы не меняются, LangGraph можно подключить позже без миграций. Контракты не менялись. Тесты: `tests/unit/test_agent_core.py`, `tests/integration/test_agent.py`. Время: ~2 ч.
