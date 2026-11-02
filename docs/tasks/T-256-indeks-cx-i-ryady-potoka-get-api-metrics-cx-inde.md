# T-256 — Индекс CX и ряды потока: GET /api/metrics/cx-index, микс каналов, поток за 24 часа, веса в settings

| Поле | Значение |
|---|---|
| Эпик | E21 Дизайн-система v2: темы, циркадный режим, «кикубари», каркас и «Обзор» [ПРОТО] |
| Субагент | `SA-Analytics` (API кабинета, CSI и ВСП, индекс CX [ЕТЗ]) |
| Оценка | S (≤ 0,5 дня) |
| Волна | 8 |
| Слой | `L3` Агент и контуры (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | нет — можно отложить |
| Статус | `in_progress` |

## Цель
Серверные данные для «Обзора» (ТЗ 14.1, 26.4).

## Разделы ТЗ (docs/TZ.md)
§14.1, §26.4

## Контракты
- `api/openapi.yaml: GET /api/metrics/cx-index`
- `settings: cx_index.weights`

## Зависимости
- Зависит от: [T-132](T-132-api-svodnoj-ekonomiki-i-metrik-dashborda.md)
- Блокирует: [T-255](T-255-ekran-obzor-overview-kpi-polosa-indeks-cx-miks-k.md)

## Что сделать
1. Функция индекса CX: формула 14.1, веса из `settings.cx_index.weights`, окно 24 сим-часа, изменение за час; чистая функция + unit-тесты на границы 0 и 100.
2. `GET /api/metrics/cx-index?run_id=` с разложением по компонентам (негатив, критичность, SLA, угроза ухода), микс каналов и ряд потока по часам; помечено «демонстрационный индекс».
3. Использовать представления `v_*`, p95 ≤ 300 мс; тесты воспроизводимости на сиде.

## Критерии приёмки
- [ ] Индекс совпадает с ручным расчётом на фикстуре; веса меняются через настройки.
- [ ] p95 ≤ 300 мс.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/unit/test_cx_index.py backend/tests/integration/test_metrics_cx_index.py
```

## Отчёт субагента
Ветка `codex/T-256-cx-index`, исходная база clean T-244 `b971710`; ordinary composition T244CI8f сохранена. [API29 semantics/proof/rollback](../reviews/T-256-cx-index-design.md), [samples/coverage/планы](../reviews/T-256-producer-proof.json). Реализованы typed readonly CX/Overview, current-only scope, weights PATCH/import, registered SLA/unknown и independent historical receipts.91functionalunit/actualPGHTTP green; native demo5000 p95 CX26.321ms/Overview23.554ms, firstGET included/порог300; analytics208/210 statements99%; make lint green429front/311mypy/drift194. Full make test/CI/review впереди, карточка не закрыта; T255/T257 отдельные stacked ветки. Нет LLM/денежных writes/DDL.
