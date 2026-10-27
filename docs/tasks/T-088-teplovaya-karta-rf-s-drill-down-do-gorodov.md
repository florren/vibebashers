# T-088 — Тепловая карта РФ с drill-down до городов

| Поле | Значение |
|---|---|
| Эпик | E7 Рабочее место CX |
| Субагент | `SA-Map` (карта РФ) |
| Оценка | L (3–4 дня) |
| Волна | 3 |
| Слой | `L4` Фронт (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `done` |

## Цель
Карта субъектов с интенсивностью сигналов/критичных/открытых инцидентов/риска ухода, клик → города → сигналы.

## Разделы ТЗ (docs/TZ.md)
§12.2 экран 2 (карта), §3.2

## Контракты
- `api/openapi.yaml: map/heat, map/regions/{code}/cities`

## Зависимости
- Зависит от: [T-086](T-086-layout-rabochego-mesta-cx-shapka-sim-chasy-panel.md), [T-011](T-011-spravochnik-subektov-i-gorodov-rf-svg-karta.md)
- Блокирует: [T-218](T-218-karta-sloj-zony-zelenaya-zheltaya-krasnaya-po-v.md), [T-242](T-242-ekran-kabinet-menedzhera-produkta-cabinet-kpi-ka.md)

## Что сделать
1. d3-geo + SVG из public/map/russia.svg; слои и окно времени; легенда; тултипы с цифрами; анимация «вспышки» при массовом сбое (WS incidents/created с mass_impact).
2. Drill-down: панель городов с точками по координатам, список сигналов города.
3. Производительность: перерисовка ≤ 16 мс при обновлении данных; корректная работа в обеих темах.

## Критерии приёмки
- [ ] Сценарий 6: ЮФО подсвечивается в течение 1 сим-минуты.
- [ ] Все 89 субъектов кликабельны, названия ru/en.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
npx playwright test e2e/map.spec.ts
```

## Отчёт субагента
Ветка `feat/b08-b14-map-metrics`. Backend `api/map.py`: `/api/map/heat` (регион = гео сигнала, иначе регион клиента; `intensity` нормирована к максимуму слоя), `/api/map/regions/{code}/cities` (город из гео по названию либо город клиента, `top_signal_ids`). Frontend `pages/workspace/MapTab.tsx`: d3-geo (коническая конформная проекция) + topojson-client, TopoJSON 83 субъектов в `src/shared/geo/russia-regions.topo.json` (источник и лицензия — README рядом), субъекты 90–95 без полигона — маркеры по центроидам из `regions`; переключатели слоя/окна/запуска, подписи значений, клик → панель региона с городами. Отклонение: отдельного `russia.svg` (T-011) нет — вместо него TopoJSON, что проще держать в сборке.
