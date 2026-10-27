# T-200 — OpenAPI 1.3 и JSON-схемы в коде: роутеры-заглушки, Pydantic, TS-типы, проверка дрейфа

| Поле | Значение |
|---|---|
| Эпик | E1 Каркас, БД, установка |
| Субагент | `SA-DB` (БД, миграции, генерация из контрактов, тесты данных) |
| Оценка | M (1–2 дня) |
| Волна | 2 |
| Слой | `L1` Базис (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `done` |

## Цель
Новые теги (feed, abs, rules, compliance, stt, demo) и схемы событий становятся кодом до реализации, чтобы фронт и бэкенд E15–E17 шли параллельно.

## Разделы ТЗ (docs/TZ.md)
§12.3, §21, §22

## Контракты
- `api/openapi.yaml`
- `events/agent/{normalization,client_match,rule_violation,instant_decision}.schema.json`
- `events/compliance/*`
- `events/sim/{review,abs}.schema.json`
- `events/demo/failover.schema.json`
- `events/ws/message.schema.json`

## Зависимости
- Зависит от: [T-006](T-006-sync-contracts-generaciya-enums-pydantic-shem-ts.md), [T-004](T-004-karkas-fastapi-konfig-logirovanie-oshibki-health.md)
- Блокирует: [T-221](T-221-migraciya-0003-i-openapi-1-4-v-kode-modeli-sqlal.md), [T-223](T-223-kontrakty-sleda-i-poiska-migraciya-0004-openapi.md)

## Что сделать
1. Роутеры-заглушки по новым тегам с ответами 501 problem+json и корректными моделями ответов; check_openapi_drift проходит для новых тегов.
2. datamodel-codegen для новых схем агента/комплаенса; TS-типы перегенерированы; ws.ts знает топики feed/abs/compliance/stt/demo.
3. Валидаторы envelope для review.*, abs.*, compliance.*, demo.failover в шине событий.

## Критерии приёмки
- [ ] make sync-contracts идемпотентен; tsc strict проходит.
- [ ] Шина отклоняет невалидные события новых семейств (тест).
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
make sync-contracts && git diff --exit-code
python scripts/check_openapi_drift.py --tags feed,abs,rules,compliance,stt,demo
```

## Отчёт субагента
Коммит B01. `scripts/gen_api_stubs.py` создал 25 роутеров по тегам (156 операций, 0 операций без покрытия) — каждая заглушка поднимает `NotImplementedYet('T-xxx')` с номером карточки реализации (таблица `CARD_BY_TAG`); существующие файлы не перезаписываются. `scripts/check_openapi_drift.py` сравнивает пути+методы OpenAPI ↔ FastAPI в обе стороны (учитывает `_IncludedRouter` FastAPI ≥0.125), подключён в CI (job `tests`) и `make lint`. Отклонения: в OpenAPI нет operationId — имена функций строятся из метода и пути.
