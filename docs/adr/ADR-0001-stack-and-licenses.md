# ADR-0001 — Стек и лицензии

| Поле | Значение |
|---|---|
| Статус | принят |
| Дата | 20.10.2026 (зафиксирован задним числом 27.10.2026) |
| Решение принял | техлид (Денис); подготовил архитектор |
| Связанные разделы | AGENTS.md §2, ТЗ 5, 20.7 № 33 |

## Контекст
Демо-MVP должен подниматься одной командой на Linux без внешних зависимостей, кроме API LLM и Telegram; команда из 1–3 человек работает через ИИ-агентов, поэтому стек должен быть распространённым и стабильным. Дополнительные материалы заказчика предлагали другие стеки (NestJS, React 19, Redis, Elasticsearch — ТЗ 20.7 № 33).

## Решение
Backend: Python 3.12, FastAPI, SQLAlchemy 2 (async), Alembic, Pydantic v2, LangGraph; БД PostgreSQL 16; frontend: React 18, Vite, TypeScript strict, Tailwind, ECharts, d3-geo, react-i18next, TanStack Query, Zustand; STT — Vosk; бот — aiogram 3; окружение — `uv`. Только открытые лицензии (MIT, BSD, Apache-2.0, PostgreSQL, MPL-2.0); GPL/AGPL/SSPL и source-available запрещены. Перечень — `docs/LICENSES.md`. Стек меняется только новым ADR.

## Последствия
Предложения заказчика по стеку не принимаются, функциональность переносится на принятый стек (поиск — PostgreSQL, графики — ECharts, анимации — CSS). React Flow разрешён, но пока не подключён (графы — собственный SVG).
