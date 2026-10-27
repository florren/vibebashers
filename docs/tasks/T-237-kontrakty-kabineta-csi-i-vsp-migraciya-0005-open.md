# T-237 — Контракты кабинета, CSI и ВСП: миграция 0005, OpenAPI, схемы, перечисления, представления

| Поле | Значение |
|---|---|
| Эпик | E19 Кабинет менеджера продукта и продуктовый разрез [ЕТЗ] |
| Субагент | `SA-DB` (БД, миграции, генерация из контрактов, тесты данных) |
| Оценка | M (1–2 дня) |
| Волна | 7 |
| Слой | `L1` Базис (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | нет — можно отложить |
| Статус | `done` |

## Цель
Контракты продуктового разреза, CSI и сети ВСП (ТЗ 13, 24–25) до начала кода (AGENTS.md §7, `contract-change`).

## Разделы ТЗ (docs/TZ.md)
§13, §24, §25, §20.7

## Контракты
- `db/migrations/0005_product_csi_branches.sql`
- `db/alembic/versions/0005_product_csi_branches.py`
- `db/schema.sql (v1.5)`
- `api/openapi.yaml 1.5.0: /api/cabinet/*, /api/roles, /api/ingest/csi, /api/csi/*, /api/branches/*, /api/metrics/cx-index, /api/signals/{id}/normalized`
- `events/ingest/csi_response.schema.json`
- `events/agent/router_tools.schema.json (+ route_to_product_team)`
- `events/common.schema.json: product_line, channel csi_survey, branch_type, branch_status`

## Зависимости
- Зависит от: [T-221](T-221-migraciya-0003-i-openapi-1-4-v-kode-modeli-sqlal.md), [T-223](T-223-kontrakty-sleda-i-poiska-migraciya-0004-openapi.md), [T-236](T-236-spravochnik-product-lines-15-napravlenij-data-pr.md)
- Блокирует: [T-238](T-238-klassifikaciya-po-napravleniyu-i-urovnyu-signala.md), [T-239](T-239-krasnye-slova-i-route-to-product-team-data-red-w.md), [T-240](T-240-korpus-product-lines-v1-i-istoriya-teksty-po-15.md), [T-241](T-241-api-kabineta-menedzhera-api-cabinet-overview-sig.md), [T-245](T-245-spravochnik-vsp-v2-rasshirenie-branches-generato.md), [T-246](T-246-priem-csi-post-api-ingest-csi-json-xlsx-csi-resp.md)

## Что сделать
1. Идемпотентный SQL 0005: `product_lines`, `signals.product_line_code`, `signals.red_words`, `regions.okato`, `product_signal_history`, канал `csi_survey`, `csi_responses`, `csi_visits_agg`, расширение `branches` и `employees`, `branch_network_history`, представления `v_signal_normalized`, `v_cabinet_kpi`; все индексы и триггеры активности.
2. Alembic 0005 с downgrade; тесты на чистой БД и на дампе v1.4; обновить шапку `schema.sql`.
3. JSON-схемы: `csi_response`, расширение `router_tools` (пятый инструмент), добавление `product_line` и `red_word` в классификацию и флаги — только вперёд.
4. OpenAPI 1.5.0 (дополняет T-223): пути кабинета, ролей, CSI, ВСП, индекса CX, нормализованного представления; заголовки `X-Cx-Role`, `X-Cx-Product-Line`; `make sync-contracts`; заглушки 501 (cross-layer).
5. Модели SQLAlchemy новых таблиц (L1), сид-хуки для baseline не трогать — их делают T-240 и T-245.

## Критерии приёмки
- [ ] `alembic upgrade head` проходит на пустой БД и на дампе v1.4; `contracts_check` зелёный.
- [ ] Старые клиенты API не ломаются (только добавления).
- [ ] PR помечен `contract-change`.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
alembic upgrade head && alembic downgrade 0004 && alembic upgrade head
python scripts/contracts_check.py && make sync-contracts && make lint
```

## Отчёт субагента
- Ветка: `feat/T-237-v15-cabinet-csi`; метка PR: `contract-change`.
- Миграция `0005_product_csi_branches.sql` (79 таблиц, head `0005`), представления `v_signal_normalized`, `v_cabinet_kpi`; OpenAPI 1.5.0 — пути кабинета/CSI/ВСП/cx-index/normalized; `csi_response.schema.json`, `route_to_product_team`, enums `product_line`, `csi_survey`, `branch_*`, флаг `red_word`.
- Заглушки 501: `cabinet`, `csi`, `branches`, расширения `ingest`/`metrics`/`signals`; модели через `make sync-contracts`.
- Проверка: `DATABASE_URL_TEST=… pytest tests/integration/test_schema.py` — 9 passed; `make contracts-check`, `make lint`, unit `make test` — зелёные.
- Зависимости T-223/T-236 в том же PR (0004, `product_lines.yaml`).
