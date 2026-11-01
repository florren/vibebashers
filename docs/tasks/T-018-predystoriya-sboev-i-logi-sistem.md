# T-018 — Предыстория сбоев и логи систем

| Поле | Значение |
|---|---|
| Эпик | E2 Справочники и генераторы данных |
| Субагент | `SA-Logs` (сбои и логи) |
| Оценка | M (1–2 дня) |
| Волна | 2 |
| Слой | `L2` Симулятор и данные (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `in_progress` |

## Цель
Сбои за 14 дней с каузальной связью к операциям и логам, включая регрессии после фиксов.

## Разделы ТЗ (docs/TZ.md)
§4.2, §4.3, §6 шаг 2

## Контракты
- `db/schema.sql: faults, system_logs`
- `events/sim/fault.schema.json`
- `events/sim/fault_regression.schema.json`

## Зависимости
- Зависит от: [T-017](T-017-produkty-klientov-i-14-dnej-operacij.md), [T-014](T-014-kody-oshibok-tipy-signalov-pravila-marshrutizaci.md)
- Блокирует: [T-020](T-020-predystoriya-signalov-incidentov-statusov-artefa.md), [T-022](T-022-testy-dannyh-no-pii-pokrytie-idempotentnost-proi.md), [T-034](T-034-generator-sboev-i-vosstanovlenij.md)

## Что сделать
1. scripts/seed/faults.py: 2–4 сбоя в сутки (длительность 10–240 мин, регион/вся страна), привязка failed-операций к сбоям по системе/времени, impact_count/affected_clients.
2. system_logs: INFO-фон + WARN/ERROR/FATAL во время сбоев с error_code, component, ссылкой на операцию; формат сообщений — как в реальных логах, без ПДн.
3. 10–15 % сбоев в предыстории — регрессии (caused_by_incident_id заполняется в T-020 после создания инцидентов).
4. Сид событий fault.* в sim_events за прошлое (для ленты и графа).

## Критерии приёмки
- [x] Каждая failed-операция во время сбоя ссылается на fault_id.
- [x] По любому сбою get_system_logs возвращает ≥ 3 ERROR-записи в окне.
- [x] Валидация событий по схемам проходит.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
python scripts/seed/faults.py --profile lite --check
```

## Отчёт субагента
WIP codex/T-018-fault-history от main 4a01734, dependency T-017 e1c6c1
влит обычным merge ca00d2f. Реализован отдельный scripts/seed/faults.py, вызов
после operations и до signals; operations.py/clients.py не менялись. Привязка
только совпавших run/system/code/time/region failed-операций; реальные counts,
INFO/WARN/ERROR/FATAL и schema-valid started/resolved events. Устранены две
причины недоступности диагностики get_system_logs: lowercase levels против DDL
и отсутствие run scope. Тест проверяет реальный инструмент для каждого сбоя.

10–15% отмечены только как regression candidates. finalize_regressions принимает
настоящие same-run incident/release bindings, проверяет release другой системы
за 1–4 часа и атомарно создаёт FK/валидное событие, повтор идемпотентен. До T-020
исторические реальные regressions отсутствуют; этот критерий не объявлен done.
Контракты/DDL/финансовые/HITL правила и зависимости не менялись.

Подробная семантика, идемпотентность и граница T-020 — data/README.md.
Проверки выполняются только в cx_fault_history_revision; исходные данные других
агентов/основного стенда не затрагиваются. Первый фиксированный полный regression: unit 814 passed/18 skipped,
integration 223 passed/4 skipped (869.63s), scenarios 41 passed/2 skipped/1 failed
(replay scenario08: key miss → fallback_mock вместо completed), compliance31passed,
frontend144passed. Assertions не ослаблены; исследование exact prompt/hash diff
и отдельные согласованные follow-up baseline+current scope/uuid5 ещё выполняются.
Ruff/format323, mypy242, contracts44/161, drift191/191, licenses526 green.
Отдельный negative test и data/README фиксируют T-014 catalog-vs-contract gap
ANTIFRAUD-FALSE-BLOCK. Модель T-018 использует8 утверждённых T-017 failure_codes,
а не заявляет проверку всех25 событийных кодов. DoD пока не выполнен.
