# T-006 — sync-contracts: генерация enums, Pydantic-схем, TS-типов, проверка дрейфа OpenAPI

| Поле | Значение |
|---|---|
| Эпик | E1 Каркас, БД, установка |
| Субагент | `SA-DB` (БД, миграции, генерация из контрактов, тесты данных) |
| Оценка | M (1–2 дня) |
| Волна | 1 |
| Слой | `L1` Базис (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `todo` |

## Цель
Контракты становятся кодом автоматически; ручное дублирование перечислений исключено.

## Разделы ТЗ (docs/TZ.md)
§13, §9.2

## Контракты
- `events/common.schema.json`
- `events/agent/*`
- `api/openapi.yaml`

## Зависимости
- Зависит от: [T-001](T-001-skelet-repozitoriya-makefile-env-example-pre-com.md)
- Блокирует: [T-032](T-032-shina-sobytij-simulyatora.md), [T-046](T-046-interfejs-llm-provajdera-i-strukturirovannyj-vyv.md), [T-076](T-076-politiki-hitl-policies-py-i-testy.md), [T-199](T-199-migraciya-0002-primenenie-modeli-sqlalchemy-i-pe.md), [T-200](T-200-openapi-1-3-i-json-shemy-v-kode-routery-zaglushk.md)

## Что сделать
1. scripts/gen_enums.py: common.schema.json → backend/app/contracts/enums.py (StrEnum) и frontend/src/shared/contracts/enums.ts.
2. datamodel-codegen → backend/app/agent/schemas.py (Pydantic v2, extra=forbid) из events/agent/*.json и events/behavior/*.json.
3. openapi-typescript → frontend/src/shared/api/types.ts; обёртка fetch с problem+json.
4. tests/unit/test_contracts_sync.py: сгенерированные файлы совпадают с текущими контрактами (fail при забытом make sync-contracts).

## Критерии приёмки
- [ ] `make sync-contracts` идемпотентен (повторный запуск не меняет файлы).
- [ ] Pydantic-модель Decision отклоняет пример с needs_human=true без human_reason.
- [ ] TS-типы компилируются в strict.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
make sync-contracts && git diff --exit-code
pytest backend/tests/unit/test_contracts_sync.py
```

## Отчёт субагента
Коммит B01. `scripts/gen_enums.py` → `app/contracts/enums.py` (41 StrEnum из `$defs` common.schema.json; TS-файл пишется при наличии `frontend/src`); `scripts/gen_schemas.py` → `app/contracts/events/<семейство>/<схема>.py` (36 модулей Pydantic v2, `extra=forbid`, схемы с перекрёстными `$ref` — пакетами) и реэкспорт в `app/{agent,compliance,rules,ingest}/schemas.py`; `scripts/gen_api_stubs.py`; `make sync-contracts` вызывает всё и `gen_models.py`. Тесты: `test_contracts_sync.py` (повторная генерация даёт тот же файл, иначе красный), `test_contract_examples.py` (все `examples` из 21 схемы валидируются моделями). Отклонения: имя корневого класса — из имени файла (заголовки русские); `zone.schema.json` → `ZoneEvent` (конфликт с перечислением `Zone`); датаmodel-codegen для `instant_decision` создаёт пакет с `_internal.py`.
