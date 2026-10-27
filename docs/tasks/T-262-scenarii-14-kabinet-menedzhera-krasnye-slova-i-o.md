# T-262 — Сценарии 14 «Кабинет менеджера: красные слова и отчёт» и 15 «CSI и ВСП»: YAML, кассеты, автотесты, блок F демо-скрипта

| Поле | Значение |
|---|---|
| Эпик | E19 Кабинет менеджера продукта и продуктовый разрез [ЕТЗ] |
| Субагент | `SA-QA` (тесты и CI) |
| Оценка | M (1–2 дня) |
| Волна | 9 |
| Слой | `L5` Качество (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | нет — можно отложить |
| Статус | `todo` |

## Цель
Приёмка кабинета, CSI и слоя ВСП (ТЗ 18, сценарии 14–15; критерии 34–39).

## Разделы ТЗ (docs/TZ.md)
§18, §24, §25, §19

## Контракты
- `data/scenarios/cabinet_red_words_report.yaml`
- `data/scenarios/csi_and_branches.yaml`

## Зависимости
- Зависит от: [T-242](T-242-ekran-kabinet-menedzhera-produkta-cabinet-kpi-ka.md), [T-249](T-249-ekran-csi-csi-tablica-zhalob-scatter-bar-po-dolz.md), [T-250](T-250-karta-sloj-vsp-markery-po-tipam-klasterizaciya-k.md), [T-239](T-239-krasnye-slova-i-route-to-product-team-data-red-w.md)
- Блокирует: —

## Что сделать
1. `cabinet_red_words_report.yaml` (14): роль `product_manager`, направление «Вклады»; жалоба с красными словами → красная полоса, HITL, `route_to_product_team`; калькулятор со ставкой 961 ₽; отчёт XLSX.
2. `csi_and_branches.yaml` (15): импорт XLSX, сигналы `csi_survey`, `/csi` (корреляции, топ-10), слой ВСП на карте, закрытое ВСП с сигналами, блок «ВСП vs Сигналы».
3. Кассеты replay, автотесты backend и Playwright; пункты меню демонстратора; блок F демо-скрипта.

## Критерии приёмки
- [ ] `make scenario ID=cabinet_red_words_report` и `ID=csi_and_branches` зелёные на кассетах.
- [ ] Блок F описан пошагово.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
make scenario ID=cabinet_red_words_report
make scenario ID=csi_and_branches
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
