# T-141 — Тестовая инфраструктура backend

| Поле | Значение |
|---|---|
| Эпик | E11 Сценарии и тесты |
| Субагент | `SA-QA` (тесты и CI) |
| Оценка | M (1–2 дня) |
| Волна | 1 |
| Слой | `L5` Качество (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `done` |

## Цель
pytest с живой PostgreSQL, фикстуры данных, mock-LLM по умолчанию, маркеры slow/llm.

## Разделы ТЗ (docs/TZ.md)
§17 E11, §19

## Контракты
- AGENTS.md §8

## Зависимости
- Зависит от: [T-005](T-005-primenenie-schema-sql-sqlalchemy-modeli-sessii.md), [T-049](T-049-mock-provajder-pravila-shablony-determinizm.md)
- Блокирует: [T-142](T-142-avtotesty-7-demo-scenariev.md), [T-145](T-145-ci-konvejer-polnogo-cikla.md), [T-222](T-222-logirovanie-i-reporting-kachestva-jsonl-zhurnal.md)

## Что сделать
1. pytest-asyncio, testcontainers-postgres (или compose-сервис в CI), фабрики данных (factory_boy/ручные), фикстура sim_clock, фикстура mock-профиля; маркеры: slow, llm (требует ключей, пропускается в CI).
2. Хелперы: run_agent_on(text, …), advance_sim(hours), assert_event(type, …).

## Критерии приёмки
- [ ] `pytest -m 'not slow and not llm'` проходит в CI за ≤ 5 мин.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest -m 'not slow and not llm'
```

## Отчёт субагента
- Ветка `feat/T-142-l5-quality` (cross-layer PR). Добавлены `backend/tests/helpers.py` (`run_agent_on`, `advance_sim`, `new_run`, `events_of`, `assert_event`, `mock_chain`, `MOCK_PROFILE`), маркеры pytest `integration/scenario/slow/llm` в `pyproject.toml`, пакет `tests/scenarios` с conftest, переиспользующим фикстуру `seeded` (alembic head + сид lite) из `tests/integration`.
- Отклонения: фабрики данных не выделялись в отдельный модуль — клиентов и операции подбирает/создаёт `app.sim.scenarios` (`pick_client`, `inject_operation`), что одинаково работает в тестах и на стенде.

Ревизия 01.11.2026, ветка `codex/cli-workflow-completion`: `make test` теперь включает ранее пропущенные `tests/compliance` и frontend vitest; `make lint` включает существующую frontend-проверку `lint-front`. Добавлены цели `test-compliance`/`test-front`. Регрессии через `make -n` проверяют включение всех четырёх backend-каталогов и frontend, а также обоих слоёв lint. Проверки окружения Node 26 документированы в README; CI остаётся на Node 22.

PR: https://github.com/florren/vibebashers/pull/150. Проверено: `NODE_OPTIONS=--no-experimental-webstorage make lint` (ruff/format/mypy, ESLint, проектный `npm run typecheck`, 144 vitest); backend unit 733 passed / 18 skipped, integration 210 passed / 2 skipped; targeted CLI 22 passed; обе frontend-сборки; contracts 44 схемы / 161 путь, OpenAPI drift 191/191, i18n 1483 ключа, owners и git diff --check. Итоговый последовательный `make test` на отдельной PostgreSQL 16 с инструментами major 16 завершён с кодом 0: unit 733 passed / 18 skipped, integration 210 passed / 2 skipped, scenarios 42 passed / 2 skipped, compliance 31 passed, frontend 144 passed; всего backend 1016 passed / 22 skipped. CI финального SHA записывается в описание PR. Параллельные unit/integration прогоны в одном checkout недопустимы: unit-тест свежести моделей временно пересоздаёт `app/contracts/events`.
