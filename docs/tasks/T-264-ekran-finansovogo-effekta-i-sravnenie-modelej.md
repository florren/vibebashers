# T-264 — Экран финансового эффекта и сравнение моделей

| Поле | Значение |
|---|---|
| Эпик | E24 Финансовый эффект запуска и сравнение моделей |
| Субагент | `SA-Economics` (экономика и калькулятор) |
| Оценка | L (3–4 дня) |
| Волна | 9 |
| Слой | `L2` Симулятор и данные (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | нет — можно отложить |
| Статус | `done` |

## Цель
Показать на /finance прогресс одного запуска и три раздельных варианта: действующая модель, вероятность оттока, вероятность с условным штрафом. GitHub #88, эпик #87.

## Разделы ТЗ (docs/TZ.md)
§14.6

## Контракты
- `api/openapi.yaml: finance/impact total/detail`
- docs/adr/ADR-0013-financial-impact.md

## Зависимости
- Зависит от: [T-131](T-131-raschet-ekonomiki-dcltv-po-incidentu.md), [T-132](T-132-api-svodnoj-ekonomiki-i-metrik-dashborda.md), [T-093](T-093-dashbord-kpi-i-blok-ekonomiki.md), [T-202](T-202-ekonomika-fee-refund-i-misselling-stroka-effekta.md)
- Блокирует: [T-265](T-265-kalibrovka-veroyatnosti-ottoka-i-dokazatelstva-s.md)

## Что сделать
1. Сопоставить входное ТЗ с ADR-0007 и отделить расчётные оценки от выручки; не менять проводки и HITL.
2. Добавить additive REST-контракты и TS-типы, периоды UTC по сим-времени, run_id без all, пагинацию и детализацию сохранённых множителей.
3. Обновлять расчёт при смене статуса без подарка; WS metrics/FINANCIAL_IMPACT_UPDATED инвалидирует снимок, polling восстанавливает пропуски.
4. UI: три варианта, редактируемые P и штраф как допущения, возвраты и отрицательный net, график, реестр, ошибки и неполные расчёты; i18n ru/en.
5. Проверить изоляцию, границы дат, отсутствие удвоения по алертам, повторное чтение, обе темы и языка.

## Критерии приёмки
- [x] Live без запуска пуст; другой запуск и открытые кейсы не попадают в итоги.
- [x] Три варианта сравниваются на одном экране и не суммируются; P не выдаётся за NLP, штраф — за факт.
- [x] Итог и временной ряд не зависят от страницы реестра; формулы доступны по клику.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
make lint && make test
cd frontend && npm run lint && npm run typecheck && npm test -- --run && npm run build
pytest backend/tests/integration/test_finance.py
```

## Отчёт субагента
Ветка `codex/financial-impact`, GitHub #88 (E24 #87). Реализованы /finance, REST total/detail (OpenAPI 1.5.2, generated TS types), read-only снимки одного запуска, периоды UTC, серверная пагинация/график и модал, три раздельных варианта, точные копейки и отдельный net, WS invalidation/reconnect/polling. Формула ADR-0007, проводки и HITL сохранены. Источник обновляет экономику при действиях агента и оператора до публикации статуса, в том числе без подарка; computed_at не старее outcome update.

Проверено локально: make lint/test — 551 unit + 103 integration + 22 scenarios passed (20 skipped в опциональных контурах); frontend lint/typecheck/build и 118 Vitest passed. contracts, OpenAPI drift, i18n, owners --allow-cross и git diff --check успешны. 21 целевая backend-проверка включена в полный набор. Скриншоты ru/en × light/dark, mobile и реальный mock/WS smoke — docs/benchmarks/financial-impact-2026-10-29/README.md. CI является обязательным gate PR перед merge.

Отклонение от общего DoD: живой GigaChat не вызывался, LLM-логика не менялась; проверен offline lite. Не измерялась demo-нагрузка/p95. P и штраф остаются допущениями по решению заказчика; калибровка и доказательства вынесены в T-265/#89. Старые карточки T-093/T-131/T-132/T-202 не закрывались автоматически. Миграций и новых зависимостей нет. Откат — revert PR.
