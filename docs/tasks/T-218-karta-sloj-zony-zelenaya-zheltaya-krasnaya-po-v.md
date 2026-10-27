# T-218 — Карта: слой «Зоны» (зелёная/жёлтая/красная) по v_map_zones, настройка порогов, счётчик «без гео», живой тикер экономики

| Поле | Значение |
|---|---|
| Эпик | E18 Приём транскриптов, роутер-инструменты, «красные фразы», зоны карты [ДТЗ] |
| Субагент | `SA-Map` (карта РФ) |
| Оценка | M (1–2 дня) |
| Волна | 4 |
| Слой | `L4` Фронт (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `done` |

## Цель
Карта показывает трёхцветные зоны с учётом негатива и сработок copilot и живой финансовый эффект (ДТЗ FR-5.1–5.4, ТЗ 12.2, 14.1, решение 20.6 п. 26, критерий 33).

## Разделы ТЗ (docs/TZ.md)
§12.2, §13, §14.1, §16.4, §19

## Контракты
- `db/schema.sql: v_map_zones, economics_settings.map_zone_thresholds`
- `events/sim/zone.schema.json`
- `events/ws/message.schema.json: zones, metrics/economics_live`
- `api/openapi.yaml: GET /api/map/zones, GET /api/metrics/economics/live, MapZone, MapZoneThresholds`

## Зависимости
- Зависит от: [T-088](T-088-teplovaya-karta-rf-s-drill-down-do-gorodov.md), [T-093](T-093-dashbord-kpi-i-blok-ekonomiki.md), [T-132](T-132-api-svodnoj-ekonomiki-i-metrik-dashborda.md), [T-207](T-207-edinaya-shema-soobscheniya-i-normalizator-ingest.md), [T-215](T-215-taksonomiya-krasnyh-fraz-semejstvo-conduct-ruden.md)
- Блокирует: [T-220](T-220-scenarii-10-transkript-roznichnogo-dialoga-i-11.md), [T-250](T-250-karta-sloj-vsp-markery-po-tipam-klasterizaciya-k.md)

## Что сделать
1. Backend: GET /api/map/zones (v_map_zones + thresholds + no_geo_count); пересчёт по событиям signal/incident/compliance_alert с дебаунсом 500 мс; событие zone.changed при смене зоны; GET /api/metrics/economics/live и WS metrics/economics_live при каждом пересчёте экономики.
2. UI: переключатель слоёв «Тепло / Зоны»; заливка субъектов по zone с палитрой #21A038 / #F1E813 / красный из темы, легенда с подписями и счётчиком «без гео»; тултип с индексами; drill-down сохраняется.
3. Настройки: /settings → Карта: yellow/red/copilot_weight/window_sim_hours (PUT economics settings).
4. Тикер над картой: CLV под риском / предотвращено / потенциальные потери, анимация изменения; обновление ≤ 2 с.
5. Тест представления на фикстуре (3 региона → green/yellow/red), e2e смены зоны в сценарии 11.

## Критерии приёмки
- [ ] Сценарий 11: регион клиента становится красным ≤ 1 с после эскалации; тикер меняется после пересчёта.
- [ ] Легенда читается без цвета (подписи и иконки).
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/integration/test_map_zones.py
npx playwright test e2e/map-zones.spec.ts
```

## Отчёт субагента
Ветка `feat/b08-b14-map-metrics`. `/api/map/zones`: индекс зоны = концентрация негатива (негативные сигналы региона / максимум по стране за окно) + `copilot_weight` × индекс сработок комплаенс-копилота по отделениям региона (`audio_sessions`→`employees`→`branches`); красная при `zone_index ≥ red` либо ≥ `critical_red` критичных инцидентов/алертов за окно. Пороги из `economics_settings.map_zone_thresholds` (поддержан старый формат `green_max/yellow_max`). Отличие от `v_map_zones`: доля негатива заменена на концентрацию — в потоке жалоб доля негатива почти везде > 60 % и карта «краснела» целиком. Frontend: режим «Зоны» с легендой и счётчиками, «без гео».
