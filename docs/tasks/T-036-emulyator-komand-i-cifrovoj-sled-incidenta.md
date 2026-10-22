# T-036 — Эмулятор команд и цифровой след инцидента

| Поле | Значение |
|---|---|
| Эпик | E3 Симулятор банка, команды, SLA |
| Субагент | `SA-Teams` (симулятор, команды, SLA) |
| Оценка | L (3–4 дня) |
| Волна | 3 |
| Слой | `L2` Симулятор и данные (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `todo` |

## Цель
Команды берут инциденты в работу, задают уточнения, пишут RCA, решают о фиксе, релизят, проверяют, закрывают, иногда ломают рядом.

## Разделы ТЗ (docs/TZ.md)
§8.3, §8.4, §4.2

## Контракты
- `events/sim/team_action.schema.json`
- `events/sim/fault_regression.schema.json`
- `db/schema.sql: team_actions, incident_artifacts`

## Зависимости
- Зависит от: [T-032](T-032-shina-sobytij-simulyatora.md), [T-013](T-013-produkty-sistemy-komandy-kanaly.md), [T-046](T-046-interfejs-llm-provajdera-i-strukturirovannyj-vyv.md), [T-058](T-058-instrumenty-zapisi-i-pobochnyh-effektov.md)
- Блокирует: [T-038](T-038-dvizhok-scenariev-yaml-i-7-demo-scenariev.md), [T-063](T-063-uzly-followup-monitor-verify-close-gift-i-otlozh.md)

## Что сделать
1. app/sim/teams.py: для каждого инцидента в routed/in_progress планировать действия по speed_profile и SLA (take в пределах take_hours с p_sla_breach на просрочку; clarify с p_clarify → статус awaiting_client через агента; rca → fix_decision → release → verify → close).
2. Артефакты: генерируются fast-моделью (GigaChat-3-Lightning) по шаблону с фактами инцидента или шаблоном Jinja при офлайне; progress_report строго в контрольные дни (д3/6/9) с вероятностью пропуска 10 % (для демонстрации sla.report_missing).
3. Регрессия: при release с p_regression → fault.regression в смежной системе того же продукта через 60–240 сим-мин; новый инцидент создаёт агент по проактивной ветке со ссылкой caused_by.
4. Смена статусов инцидента — только через инструмент update_incident (история статусов, NOTIFY).

## Критерии приёмки
- [ ] Инцидент hard/low проходит весь путь за ≤ 10 рабочих дней с тремя отчётами (сценарий 7).
- [ ] Доля регрессий 10–15 % на 100 релизах (тест статистики).
- [ ] Артефакты читабельны, без ПДн, на русском.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/unit/test_teams.py
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
