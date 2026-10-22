# T-132 — API сводной экономики и метрик дашборда

| Поле | Значение |
|---|---|
| Эпик | E10 Бенчмарки и экономика |
| Субагент | `SA-Economics` (экономика и калькулятор) |
| Оценка | M (1–2 дня) |
| Волна | 3 |
| Слой | `L2` Симулятор и данные (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `todo` |

## Цель
Агрегаты для дашборда: KPI ТЗ 14.1 и экономика по группам и окнам.

## Разделы ТЗ (docs/TZ.md)
§14.1, §14.4

## Контракты
- `api/openapi.yaml: metrics/dashboard, metrics/economics`

## Зависимости
- Зависит от: [T-040](T-040-servis-zapuskov-emulyacii-sim-runs-run-id-rezhim.md), [T-131](T-131-raschet-ekonomiki-dcltv-po-incidentu.md), [T-037](T-037-sla-dvizhok.md), [T-161](T-161-parametricheskaya-model-sostoyanij-klienta.md)
- Блокирует: [T-042](T-042-itogovye-metriki-zapuska-summary-i-eksport.md), [T-093](T-093-dashbord-kpi-i-blok-ekonomiki.md), [T-218](T-218-karta-sloj-zony-zelenaya-zheltaya-krasnaya-po-v.md)

## Что сделать
1. SQL-агрегаты (через представления и индексы), кэш 5 с; метрики удержания по исходам/психотипам, account_closures, regression_share, twin_satisfaction_avg.

## Критерии приёмки
- [ ] Все метрики принимают run_id (current по умолчанию, id или all); данные baseline в счётчики текущего запуска не попадают; тест: два запуска с разными данными дают разные ответы.
- [ ] Ответ ≤ 300 мс на demo-профиле.
- [ ] Цифры сверяются с прямыми SQL в тестах.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/integration/test_metrics_api.py
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
