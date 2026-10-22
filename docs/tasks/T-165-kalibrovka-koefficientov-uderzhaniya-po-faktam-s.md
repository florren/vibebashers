# T-165 — Калибровка коэффициентов удержания по фактам симуляции

| Поле | Значение |
|---|---|
| Эпик | E14 Поведение клиентов и калькулятор «Факт» |
| Субагент | `SA-Economics` (экономика и калькулятор) |
| Оценка | S (≤ 0,5 дня) |
| Волна | 4 |
| Слой | `L2` Симулятор и данные (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | нет — можно отложить |
| Статус | `todo` |

## Цель
Режим simulated: коэффициенты из v_retention_by_outcome с контролем выборки.

## Разделы ТЗ (docs/TZ.md)
§14.4, §14.5, §20.2 п. 4

## Контракты
- `api/openapi.yaml: metrics/economics/calibrate`
- `db/schema.sql: v_retention_by_outcome, economics_settings`

## Зависимости
- Зависит от: [T-161](T-161-parametricheskaya-model-sostoyanij-klienta.md), [T-131](T-131-raschet-ekonomiki-dcltv-po-incidentu.md)
- Блокирует: [T-166](T-166-vkladka-kalkulyatora-fakt-po-simulyacii-api-ui-e.md)

## Что сделать
1. app/economics/calibration.py: расчёт долей по классам исхода, минимальная выборка 10 (иначе manual с пометкой), сохранение снимка в settings.economics.calibration_snapshot; POST calibrate переключает режим и пересчитывает prevented для окна.
2. Сравнение assumptions_vs_fact для вкладки «Факт».

## Критерии приёмки
- [ ] Переключение режима меняет prevented_loss на дашборде и в карточках; обратное переключение возвращает ручные значения.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/unit/test_calibration.py
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
