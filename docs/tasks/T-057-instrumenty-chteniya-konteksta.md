# T-057 — Инструменты чтения контекста

| Поле | Значение |
|---|---|
| Эпик | E5 Агент LangGraph |
| Субагент | `SA-Agent` (агент LangGraph) |
| Оценка | M (1–2 дня) |
| Волна | 2 |
| Слой | `L3` Агент и контуры (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `todo` |

## Цель
Инструменты get_client_profile, get_client_products, get_recent_operations, get_system_logs, find_related_incidents, search_similar_signals.

## Разделы ТЗ (docs/TZ.md)
§9.2, §6 шаг 2

## Контракты
- `events/agent/tool_call.schema.json`

## Зависимости
- Зависит от: [T-056](T-056-agentstate-graf-langgraph-checkpointer-zapusk-po.md), [T-005](T-005-primenenie-schema-sql-sqlalchemy-modeli-sessii.md)
- Блокирует: [T-058](T-058-instrumenty-zapisi-i-pobochnyh-effektov.md), [T-059](T-059-uzly-ingest-normalize-identify-client-gather-con.md), [T-173](T-173-matching-klienta-po-kosvennym-dannym-match-clien.md)

## Что сделать
1. Реализация как LangChain tools с Pydantic-аргументами; результаты компактные (ограничение строк, маскирование), время выполнения в tool_calls.
2. find_related_incidents: по error_code/system/product/region в окне 4 сим-часа + открытые инциденты клиента.
3. search_similar_signals: trigram (pg_trgm) по тексту за 48 сим-часов; pgvector — опционально за флагом.

## Критерии приёмки
- [ ] Каждый инструмент покрыт тестом с фикстурами; результат ≤ 4 КБ.
- [ ] Записи tool_calls валидны по схеме.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/unit/test_tools_read.py
```

## Отчёт субагента
Ветка `feat/b04-agent`. `backend/app/agent/tools/base.py` — ToolContext (conn/run_id/agent_run_id/sim_time/llm_source), декоратор `@tool(name)`: каждая запись ToolCall валидируется по `contracts/events/agent/tool_call.schema.json`, попадает в agent_steps.tool_calls; `tools/read.py`: get_client_profile (сегмент, психотип, first_response_min, состояние, согласия, маскированные контакты), get_client_products, get_recent_operations (72 сим-ч, с fault_id), get_system_logs (активные сбои + system_logs), find_related_incidents (окно дедупа 4 сим-ч по error_code/системе/региону + открытые инциденты клиента), search_similar_signals (поиск по ключевым словам regex + история клиента 7/14 дней). **Отклонение:** без pg_trgm (расширения нет в БД) — похожесть по пересечению слов; достаточно для демо, trgm — опционально позже. Время: ~40 мин.
