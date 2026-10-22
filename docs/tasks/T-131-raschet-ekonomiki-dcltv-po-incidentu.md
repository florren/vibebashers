# T-131 — Расчёт экономики dCLTV по инциденту

| Поле | Значение |
|---|---|
| Эпик | E10 Бенчмарки и экономика |
| Субагент | `SA-Economics` (экономика и калькулятор) |
| Оценка | M (1–2 дня) |
| Волна | 2 |
| Слой | `L2` Симулятор и данные (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `done` |

## Цель
Единственная реализация формулы ТЗ 14.4 с развёрткой и пересчётом при смене статуса.

## Разделы ТЗ (docs/TZ.md)
§14.4, §0.4, §20.2 п. 4–5

## Контракты
- `db/schema.sql: incident_economics, dcltv_rates, economics_settings`
- `api/openapi.yaml: incidents/{id}/economics`

## Зависимости
- Зависит от: [T-005](T-005-primenenie-schema-sql-sqlalchemy-modeli-sessii.md), [T-015](T-015-shablony-uvedomlenij-spravochnik-podarkov-stavki.md)
- Блокирует: [T-020](T-020-predystoriya-signalov-incidentov-statusov-artefa.md), [T-090](T-090-kartochka-incidenta.md), [T-132](T-132-api-svodnoj-ekonomiki-i-metrik-dashborda.md), [T-133](T-133-ekran-kalkulyator-poter-dopuscheniya-v-stile-biz.md), [T-164](T-164-uhod-klienta-churn-events-incident-account-closu.md), [T-165](T-165-kalibrovka-koefficientov-uderzhaniya-po-faktam-s.md), [T-186](T-186-schetchik-narushenij-mashina-sostoyanij-sessii-a.md), [T-202](T-202-ekonomika-fee-refund-i-misselling-stroka-effekta.md)

## Что сделать
1. app/economics/dcltv.py: resolve_rate(incident) по maps_to (продукт → система → канал → fallback bank_average), premium_addon для premium/vip/ultra_vip, affected_count (mass_impact), potential/prevented/realized по outcome_class и retention_factors (manual или simulated из v_retention_by_outcome при выборке ≥ 10).
2. formula_ru и breakdown для карточки; пересчёт по триггеру смены статуса/outcome и по sla.tick для открытых (at_risk).
3. Инструмент compute_economics для агента (предпросмотр в decision).

## Критерии приёмки
- [ ] Юнит-тесты на все ветки ставок и коэффициентов; пример из ТЗ 14.4 (12 клиентов, вклад, VIP) даёт 631,52 ₽.
- [ ] Непокрытая система → bank_average.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/unit/test_dcltv.py
```

## Отчёт субагента
Ветка `feat/b08-b14-map-metrics`. `app/economics/dcltv.py`: `pick_rate` (продукт+сегмент → продукт → система+op_type → система → канал → fallback), `compute` (пример ТЗ 12 × 10 % × 50 % × (961 + 91,53) = 631,52 ₽ — в unit-тесте), `outcome_of`, `compute_incident` (upsert `incident_economics`, обновляет `incidents.outcome_class`), `recompute` (устаревшие и открытые), для `misselling` — `misselling_case_cost_rub` без долей. `GET /api/incidents/{id}/economics` и поле `economics` в карточке инцидента. Возвраты из Mock-АБС учитываются как `refund_amount_rub`/`net_effect_rub`.
