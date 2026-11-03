# Native catalog facts и общая эвристика product/system

## RED и причина

В actual demo5000 runtime financial guard отклонил native service incident:
`create_incident → update_incident → refresh_service_impacts → native_service_cohort`.
Проверка cohort возвращала0, хотя producer исходно подтвердил actual failed operation.

`_postcheck_classification` сначала сохраняет проверенные native product/system/error,
затем общая эвристика PRODUCT_SYSTEMS переписывала shared system. Каталог разрешает
PROMO-ELIGIBILITY-FAIL/debit_card/promo_engine, NOTIF-OTP-MISSING/credit/notification_gw
(продукт из единственного фактического cohort), ABS-BALANCE-MISMATCH/debit_card/core_abs.
Грубый heuristic path не включает эти допустимые комбинации.

RED:3 native unit failed/3 ordinary controls passed; все3 настоящих PG producer→graph
cases упали на неизменном money guard. Это не повод отключать guard.

## Изменение и граница

Одна production-условная проверка: heuristic product/system repair применяется только
без проверенного `context.proactive_fault`. Native scope по-прежнему получается через
producer lineage, current own-run clock и actual failed operations; один origin/text
не даёт эту границу. Обычный непроверенный вход сохраняет прежнюю эвристику.

Существующий graph теперь может маршрутизировать и оценить эти валидные faults,
которые раньше ошибочно завершались failed. Он использует существующие routing rules,
каталог ставок и dcltv.compute_incident. Формулы, значения ставок, бюджеты, выплаты,
HITL/consent и guards invalid/future/foreign facts не меняются. API/DDL/event schemas
без изменений. Настоящих внешних вызовов и записей в primary DB нет.

## Проверки

- GREEN13unit:6 native/ordinary matrix +7 existing incident matching regressions.
- GREEN15PG:3 shared-system +9 negative money guards +3 HITL cases,107.89s.
- Ruff и strictmypy328source files passed; все3 прежних generic controls сохраняют эвристику.
- Критическая условная ветка покрыта native=True/False для всех3 combinations;
  native PG дополнительно подтверждает actual cohort1 и отсутствие ledger entries.
- Full unit2185passed/19штатных skipped,77.30s; contracts48schemas/167paths и owners --allow-cross passed.
- Изменённая production condition проверена в обе стороны native=True/False; новая ветка исполнена во всех3 native cases.
- Full CI и final composition gates обязательны до merge.

## Review / rollback

Требуется согласование по AGENTS.md §5.1: «всё, что касается денег и HITL».
PR #214 про часы/counter не покрывает это исправление classification.
Откат одной проверки возвращает ошибочный heuristic rewrite и прежний fail-closed
отказ guard. История, failed AgentRun и старые checkpoints автоматически не исправляются;
для повторной приёмки используется новый native run. Старые факты не подменяются.
