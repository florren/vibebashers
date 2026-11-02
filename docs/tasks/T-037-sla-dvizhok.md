# T-037 — SLA-движок

| Поле | Значение |
|---|---|
| Эпик | E3 Симулятор банка, команды, SLA |
| Субагент | `SA-Teams` (симулятор, команды, SLA) |
| Оценка | M (1–2 дня) |
| Волна | 3 |
| Слой | `L2` Симулятор и данные (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `todo` |

## Цель
Контроль сроков фикса, взятия в работу, первого ответа и промежуточных отчётов с эскалациями.

## Разделы ТЗ (docs/TZ.md)
§8.2, §8.3, §3.1

## Контракты
- `events/sim/sla.schema.json`
- `db/schema.sql: incidents (sla_*, report_due_sims), followups`

## Зависимости
- Зависит от: [T-031](T-031-simclock-sim-state-i-upravlenie-simulyaciej.md), [T-032](T-032-shina-sobytij-simulyatora.md), [T-014](T-014-kody-oshibok-tipy-signalov-pravila-marshrutizaci.md)
- Блокирует: [T-038](T-038-dvizhok-scenariev-yaml-i-7-demo-scenariev.md), [T-089](T-089-doska-i-tablica-incidentov-s-indikatorami-sla.md), [T-092](T-092-vkladki-otlozhennye-komandy-uvedomleniya.md), [T-132](T-132-api-svodnoj-ekonomiki-i-metrik-dashborda.md), [T-144](T-144-proverka-proizvoditelnosti-profilya-demo.md)

## Что сделать
1. Тик каждые 15 сим-минут: sla.tick со сводкой; warning при остатке < 25 %; breached → флаг, статус escalated, уведомление команде и CX, пересчёт экономики; report_due/report_missing по report_due_sims; take_overdue; first_response_overdue по сегменту.
2. Эскалация: cx_lead при breached и при report_missing; запись в incident_status_history.
3. Публикация incidents/sla_warning|sla_breached в WS; обновление outcome_class при закрытии (closed_in_sla / closed_late / closed_with_regression / closed_in_sla_with_gift).

## Критерии приёмки
- [ ] Сроки считаются в рабочих днях (тест: инцидент в пятницу 17:00 с fix_days=1 истекает в понедельник 17:00).
- [ ] Пропуск отчёта порождает sla.report_missing и предупреждение в UI.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/unit/test_sla.py
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._


### Ревизия 2026-11-02: durable план до первого действия

Кандидат в `codex/T-037-durable-team-plan` от T161 `9bba1d9`: typed native `team.plan` и `team.runtime_started`, атомарные plan/RNG tick, чтение legacy action facts, fail-closed неизвестный pre-action план; DDL и SLA числа/due times не изменены. Исправлен доказанный restart gap без fake take/report.

Основной PG/OS/lifecycle/restore/reset-day набор 43 passed; дополнительные stale/corrupt legacy 3 passed; actual PG16 dump/restore clone 1 passed. Full unit 1727 passed /18 skipped; changed-executable line coverage131/131; Ruff/mypy/contracts/licenses зелёные. Подробности, ограничения, source hashes и rollback: [кандидат review](../reviews/T-037-durable-plan-candidate.md).

Статус `todo` и DoD не закрыты: final scenarios/compliance/полная composition CI и обязательный human event/runtime compatibility review ещё нужны. Техническое разрешение root не является пользовательским одобрением legacy policy. UI SLA warning этим кандидатом не менялся; отдельный новый UI proof не заявлен.
