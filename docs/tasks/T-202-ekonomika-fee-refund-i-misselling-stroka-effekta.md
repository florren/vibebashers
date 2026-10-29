# T-202 — Экономика fee_refund и misselling, строка эффекта, настройка misselling_case_cost_rub

| Поле | Значение |
|---|---|
| Эпик | E10 Бенчмарки и экономика |
| Субагент | `SA-Economics` (экономика и калькулятор) |
| Оценка | S (≤ 0,5 дня) |
| Волна | 4 |
| Слой | `L2` Симулятор и данные (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | нет — можно отложить |
| Статус | `todo` |

## Цель
Прямая стоимость возврата и стоимость случая мисселлинга в расчётах; строка «вернули 450 ₽, сохранили ≈ N ₽» (ТЗ 14.4).

## Разделы ТЗ (docs/TZ.md)
§14.4, §14.5

## Контракты
- `db/schema.sql: incident_economics.refund_amount_rub, economics_settings.misselling_case_cost_rub`
- `api/openapi.yaml: settings/economics, incidents/{id}/economics`

## Зависимости
- Зависит от: [T-131](T-131-raschet-ekonomiki-dcltv-po-incidentu.md), [T-171](T-171-mock-abs-scheta-tarify-provodki-sid-i-invariant.md), [T-186](T-186-schetchik-narushenij-mashina-sostoyanij-sessii-a.md)
- Блокирует: [T-264](T-264-ekran-finansovogo-effekta-i-sravnenie-modelej.md)

## Что сделать
1. fee_refund: potential по dCLTV, prevented минус refund_amount_rub; misselling: potential = misselling_case_cost_rub (настраивается, помечено «требует согласования»), prevented при decision=go до закрытия сделки.
2. effect_line_ru для постов и инцидентов; вкладка «Факт» учитывает новые типы; экспорт.

## Критерии приёмки
- [ ] Карточки fee_refund и misselling показывают развёрнутый расчёт.
- [ ] Изменение misselling_case_cost_rub пересчитывает открытые инциденты.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/unit/test_economics_v13.py
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
