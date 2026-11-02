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
- [x] Индекс совпадает с ручным расчётом на фикстуре; веса меняются через настройки.
- [x] p95 ≤ 300 мс.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/unit/test_cx_index.py backend/tests/integration/test_metrics_cx_index.py
```

## Отчёт субагента
Ветка `codex/T-256-cx-index`, исходная база clean T-244 `b971710`; ordinary composition T244CI8f сохранена. [API29 semantics/proof/rollback](../reviews/T-256-cx-index-design.md), [samples/coverage/планы](../reviews/T-256-producer-proof.json). Реализованы typed readonly CX/Overview, current-only scope, weights PATCH/import, registered SLA/unknown и independent historical receipts.91functionalunit/actualPGHTTP green; native demo5000 p95 CX26.321ms/Overview23.554ms, firstGET included/порог300; analytics208/210 statements99%; make lint green429front/311mypy/drift194. Full make test/CI/review впереди, карточка не закрыта; T255/T257 отдельные stacked ветки. Нет LLM/денежных writes/DDL.

Полный frozen-source1968631 `make test` exit0: backend2770passed/24skip (2024unit+672PG+43scenarios+31compliance), frontend429/61files, bot43. Runtime и API не менялись после freeze; дальнейший commit — только proof/docs. Последний DoD checkbox оставлен открытым до parent review/composed CI/PR, статусin_progress. Реальные внешние провайдеры не вызывались: reader намеренно readonly/BombLLM.


Дополнение проверки temporal scope: defensive409 для future started/finished/native observed evidence, upstream T041 c47 ordinary composition,9native/HTTPcontrol+shutdown tests green44.11s; functional95green42.38s/224of226coverage (source-qualified c92). Finalad33native demo5000 p95 CX27.997ms/Overview25.815ms,30GET×2firstincluded, no warmup/tracer,300msguard unchanged, GETfingerprints unchanged. API29 до exactheadCI/parentchain/review остаётся in_progress; исторический fullbackend относится к1968631. Полные raw samples/hash/границы — producer-proof/design docs.

Root composition PR199+PR200: API28/29 schemas и переводы сохранены строгим union,
internal service fixture использует native authority. 102functional60.43s
source-qualified byte-identical **весьbackend/app**; root make lint444frontend,
Ruff550/mypy323,bot12/5,drift196/196,contracts48/166. Старый full196 не переносится
на новый source; новый exact CI/merge dependency ещё обязательны, карточка не done.
