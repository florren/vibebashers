# T-248 — API аналитики CSI и ВСП: корреляции, scatter, должности, box plot стажа, топ-10 ВСП, тепловая карта, «ВСП vs Сигналы»

| Поле | Значение |
|---|---|
| Эпик | E20 CSI-аналитика и сеть ВСП [ЕТЗ] |
| Субагент | `SA-Analytics` (API кабинета, CSI и ВСП, индекс CX [ЕТЗ]) |
| Оценка | L (3–4 дня) |
| Волна | 9 |
| Слой | `L3` Агент и контуры (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | нет — можно отложить |
| Статус | `in_progress` |

## Цель
Серверная часть ЕТЗ FR-8.1–8.7 и блока 8.4 (ТЗ 25.3, 25.5).

## Разделы ТЗ (docs/TZ.md)
§25.3, §25.5, §16.4

## Контракты
- `api/openapi.yaml: /api/csi/*, /api/branches/*`

## Зависимости
- Зависит от: [T-245](T-245-spravochnik-vsp-v2-rasshirenie-branches-generato.md), [T-246](T-246-priem-csi-post-api-ingest-csi-json-xlsx-csi-resp.md), [T-247](T-247-korpus-csi-csi-v1-300-zhalob-csi-visits-agg-znam.md)
- Блокирует: [T-249](T-249-ekran-csi-csi-tablica-zhalob-scatter-bar-po-dolz.md), [T-250](T-250-karta-sloj-vsp-markery-po-tipam-klasterizaciya-k.md)

## Что сделать
1. `/api/csi/analytics`: корреляции (вероятность по корзинам, коэффициент Спирмена, размер выборки), scatter «ожидание × обслуживание» (цвет — уровень), распределение по должностям, квартили стажа «с жалобами / без», тепловая карта регионов, топ-10 ВСП; фильтры ВСП и регион.
2. `/api/branches`, `/api/branches/{code}` (карточка: адрес, режим, сигналы, CSI-метрики), `/api/branches/analytics`: сигналов на 1 ВСП по регионам, регионы с дефицитом (порог в настройках), динамика сети 12 мес., сигналы в зонах закрытия (90 дней).
3. Видимость ВСП по направлению менеджера (`product_line_codes`); HTTP-кэш 24 ч для справочника.
4. Тесты на фикстурах с известными значениями; p95 ≤ 300 мс на demo; EXPLAIN.

## Критерии приёмки
- [ ] Значения корреляций и квартилей совпадают с эталонными расчётами на фикстуре.
- [ ] Менеджер направления видит только его ВСП (режим `strict`).
- [ ] p95 ≤ 300 мс.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/integration/test_csi_analytics.py backend/tests/integration/test_branches_api.py
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._


## Промежуточный checkpoint: математическое ядро

Ветка codex/T-248-csi-analytics. Реализованы Spearman с ties/missing и квартили R7 без новых зависимостей;20 unit/actual-PG reference tests passed2,14с,52/52 statements, Ruff/mypy green. API/DDL/денежные правила не менялись; endpoint остаётся прежним501. Знаменатели требуют отдельного run/cohort provenance, concrete API28/DDL20 ещё не реализованы и не утверждены. План и ограничения: docs/reviews/T-248-statistics-checkpoint.md.


## API28 / actual0020 checkpoint

CSI и branch read-only API реализованы локально; strict scope, typed DTO, current-only metrics, integrity/unknown и backup проверены.49 PG composition passed152.70с, schema/install15passed и отдельный dump/restore1passed, core/bounds29passed. Initial demo5000 p95≤34.575мс с15 actual plans; final-source performance/full suite/coverage/CI и human API/DDL review ещё требуются. Детали и честные source-specific границы: docs/reviews/T-248-api28-checkpoint.md. Статус остаётся in_progress; T-249/T-250 не закрыты.

### Актуальная композиция API28/DDL20

Read-only CSI/branches, scoped cohort provenance, R7 min/max, календарные границы
и точные CSI/ВСП Trace links реализованы; parent197 ordinarily composed.
152unit/actualPG passed429.61с, new443/476=93.07%; native120GET/16EXPLAIN,
p95≤28.506мс, fingerprints unchanged. Full lint420frontend/Ruff535/mypy318,
contracts48/165 и drift195 green. [Границы, source hashes и откат](../reviews/T-248-contract-review.md).
UI T249/T250/T262 и полный exact-head CI остаются отдельными обязательствами;
карточка целиком не объявляется закрытой до завершения проверки PR/parents.
