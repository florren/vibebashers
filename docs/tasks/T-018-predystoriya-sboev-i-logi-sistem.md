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
Реализовано в codex/T-018-fault-history от main 4a01734 с обычным merge
T-017 e1c6c1 (ca00d2f). Генератор scripts/seed/faults.py вызывается после
operations и до signals: 14 последовательных 24-часовых окон, 2–4 сбоя в сутки,
10–240 минут, регион/вся страна. Меняется только fault_id совпавших failed
операций (run/system/code/time/region); статусы, ошибки, суммы и даты T-017
сохранены. operations.py/clients.py, контракты и финансовые/HITL правила не менялись.

Есть INFO-фон, WARN/ERROR/FATAL и реальные request logs, counts по связанным
операциям/клиентам, валидные started/resolved events. Инструмент get_system_logs
исправлен на контрактные uppercase levels и baseline+current scope с исключением
других free/scenario/live runs. UUID5 namespace фиксирован; события одного fault
имеют общий correlation, повтор после очистки с тем же seed/ID воспроизводим.
Идемпотентность/rollback и точный reset-marker prefix проверены на реальном CLI.

**Граница T-020 открыта:** 10–15% — только regression candidates, не реальные
регрессии. finalize_regressions атомарно проверяет настоящие incident/release
bindings одного run, другую систему и задержку 1–4 часа, затем заполняет FK и
создаёт валидное событие; повтор идемпотентен. В seed demo пять кандидатов из 41,
реальных регрессий пока 0. Поэтому общий статус не отмечен done.

Проверки в отдельной cx_fault_history_revision, без рабочих БД и внешних LLM:
полный первичный integration 223 passed/4 skipped (869.63s), compliance 31 passed;
после follow-up полный unit 815 passed/18 skipped (26.42s), повтор затронутых
integration/agent/trace и ВСЕХ scenarios 70 passed/2 skipped (253.07s).
Frontend 144 passed, eslint/tsc; ruff/format 324 files, mypy 242 files,
contracts 44 schemas/161 paths, drift 191/191 и licenses 526 distributions green.
Stdlib trace: новый faults.py 88%; все 4 изменённые строки get_system_logs
исполнены реальными DB-проверками (100%). Новых зависимостей нет.

Первичный scenarios выявил честный replay miss из-за T-017 bank-context drift.
Общий immutable replay_bank_v1 fixture с source hash 174508… сохранён для
replay08 и trace12/13; отдельный тест проверяет changed-seed→honest miss.
Исходные completed/replay/ledger/client_lane assertions сохранены; кассеты,
ответы и usage не менялись. Доказательство относится к старому contract.
Отдельный T-014 gap ANTIFRAUD-FALSE-BLOCK/regex не скрыт: T-018 использует
8 утверждённых failure_codes, а не заявляет валидацию всех 25 fault codes.
Новый common.schema пока не включён и требует отдельного review/нового разрешённого
реального record; совместимость со stale кассетами не заявляется.

Полный demo5000 (T-017+T-018), включая dump: 20.947s, операций 600000,
failed 5910, связанных 218, сбоев 41, ERROR logs 341. Это измерение локального
shared PostgreSQL 16 testcontainer, не обещание времени другого runner.
[Машинный отчёт](../reviews/T-018-demo5000.json); семантика — data/README.md.
Финальный required CI/merge выполняет основной агент; T-020 ещё должен завершить
реальную историческую регрессию. Поэтому общий DoD checkbox оставлен открытым.
