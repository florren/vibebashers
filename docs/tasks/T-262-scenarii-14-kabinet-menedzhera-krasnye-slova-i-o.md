# T-262 — Сценарии 14 «Кабинет менеджера: красные слова и отчёт» и 15 «CSI и ВСП»: YAML, кассеты, автотесты, блок F демо-скрипта

| Поле | Значение |
|---|---|
| Эпик | E19 Кабинет менеджера продукта и продуктовый разрез [ЕТЗ] |
| Субагент | `SA-QA` (тесты и CI) |
| Оценка | M (1–2 дня) |
| Волна | 9 |
| Слой | `L5` Качество (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | нет — можно отложить |
| Статус | `in_progress` |

## Цель
Приёмка кабинета, CSI и слоя ВСП (ТЗ 18, сценарии 14–15; критерии 34–39).

## Разделы ТЗ (docs/TZ.md)
§18, §24, §25, §19

## Контракты
- `data/scenarios/cabinet_red_words_report.yaml`
- `data/scenarios/csi_and_branches.yaml`

## Зависимости
- Зависит от: [T-242](T-242-ekran-kabinet-menedzhera-produkta-cabinet-kpi-ka.md), [T-249](T-249-ekran-csi-csi-tablica-zhalob-scatter-bar-po-dolz.md), [T-250](T-250-karta-sloj-vsp-markery-po-tipam-klasterizaciya-k.md), [T-239](T-239-krasnye-slova-i-route-to-product-team-data-red-w.md), [T-238](T-238-klassifikaciya-po-napravleniyu-i-urovnyu-signala.md)
- Блокирует: —

## Что сделать
1. `cabinet_red_words_report.yaml` (14): роль `product_manager`, направление «Вклады»; жалоба с красными словами → красная полоса, HITL, `route_to_product_team`; калькулятор со ставкой 961 ₽; отчёт XLSX.
2. `csi_and_branches.yaml` (15): импорт XLSX, сигналы `csi_survey`, `/csi` (корреляции, топ-10), слой ВСП на карте, закрытое ВСП с сигналами, блок «ВСП vs Сигналы».
3. Кассеты replay, автотесты backend и Playwright; пункты меню демонстратора; блок F демо-скрипта.
4. Сохранить catalog IDs/numbers 1..33; новые entries 34/35 несут tz_number 14/15. Mock foundation проверяется отдельно, mandatory UI/replay not_verified не превращаются в общий passed.
5. Legal input остаётся pending HITL до решения человека; отдельный ordinary input проверяет native product route. Runtime никогда не принимает human_decision ради показа.
6. CSI preparation: 300 canonical scoped rows + 1 explicit synthetic closed-branch row без выдуманного denominator; реальный XLSX parser/normalizer, два целиком зарезервированных namespace blocks, source hashes и atomic retry.

## Критерии приёмки
- [ ] `make scenario ID=cabinet_red_words_report` и `ID=csi_and_branches` зелёные на кассетах.
- [x] Блок F описан пошагово.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
make scenario ID=cabinet_red_words_report
make scenario ID=csi_and_branches
```

## Отчёт субагента
Ветка `codex/T-262-scenarios`. Native Mock foundation реализован отдельно от полной приёмки: catalog34/35 без изменения1..33;301CSI rows/2reserved blocks, реальные XLSX/normalizer/cohort, atomic retry; legal pending HITL и отдельный ordinary product route; metrics961/настоящий report. Общий passed=False до UI/replay; кассеты не выдумывались, human decisions не принимались. [Конкретные границы, recovery и план replay](../reviews/T-262-scenario-foundation.md). Проверки:110 pure +25 focused coverage tests (9 unit/16 actual PG), frontend429, lint/contracts/licenses, Alembic zero drift — green; coverage175/189=92.59%. Полный backend suite/CI, UI/replay и manual legal continuation остаются непроверенными; карточка не done.
