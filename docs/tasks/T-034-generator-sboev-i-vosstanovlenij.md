# T-034 — Генератор сбоев и восстановлений

| Поле | Значение |
|---|---|
| Эпик | E3 Симулятор банка, команды, SLA |
| Субагент | `SA-Logs` (сбои и логи) |
| Оценка | M (1–2 дня) |
| Волна | 2 |
| Слой | `L2` Симулятор и данные (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `todo` |

## Цель
Псевдослучайные сбои подсистем с логами, регионами и затронутыми клиентами.

## Разделы ТЗ (docs/TZ.md)
§4.2, §4.3

## Контракты
- `events/sim/fault.schema.json`
- `db/schema.sql: faults, system_logs`

## Зависимости
- Зависит от: [T-032](T-032-shina-sobytij-simulyatora.md), [T-018](T-018-predystoriya-sboev-i-logi-sistem.md)
- Блокирует: [T-038](T-038-dvizhok-scenariev-yaml-i-7-demo-scenariev.md), [T-039](T-039-proaktivnaya-vetka-sboj-uvedomleniya-zatronutym.md)

## Что сделать
1. Интенсивность 2–4/сутки (настраивается), выбор системы/кода по весам, длительность, регион(ы), severity; события fault.started/escalated/resolved.
2. Генерация system_logs во время сбоя (ERROR каждые 1–3 сим-мин + INFO-фон).
3. affected_client_ids_sample в событии для проактивной ветки агента; impact_count обновляется при op.failed.
4. Ручной запуск сбоя из UI/сценария (используется в T-038).

## Критерии приёмки
- [ ] Сбой виден в логах, операциях, карте (регион) и ленте событий в течение 1 сим-минуты.
- [ ] fault.resolved закрывает сбой и прекращает failed-операции.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/unit/test_gen_faults.py
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
