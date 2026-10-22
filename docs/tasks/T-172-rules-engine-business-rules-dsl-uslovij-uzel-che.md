# T-172 — Rules Engine: business_rules, DSL условий, узел check_rules и четыре правила v1

| Поле | Значение |
|---|---|
| Эпик | E15 Внешние площадки и автономный возврат [BRD] |
| Субагент | `SA-ABS` (Mock-АБС и бизнес-правила [BRD]) |
| Оценка | M (1–2 дня) |
| Волна | 2 |
| Слой | `L2` Симулятор и данные (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `done` |

## Цель
Детерминированная проверка нарушений перед решением агента (ТЗ 9.6): деньги двигаются только при matched; LLM получает правила как факт.

## Разделы ТЗ (docs/TZ.md)
§1.4, §9.1, §9.6

## Контракты
- `db/schema.sql: business_rules, rule_evaluations`
- `events/rules/rule_condition.schema.json`
- `events/agent/rule_violation.schema.json`
- `api/openapi.yaml: rules/*`

## Зависимости
- Зависит от: [T-171](T-171-mock-abs-scheta-tarify-provodki-sid-i-invariant.md), [T-056](T-056-agentstate-graf-langgraph-checkpointer-zapusk-po.md)
- Блокирует: [T-174](T-174-bystryj-put-agenta-uslovnoe-rebro-act-instant-st.md), [T-175](T-175-instrumenty-refund-fee-find-affected-clients-get.md)

## Что сделать
1. app/rules/engine.py: интерпретатор подмножества JSON-логики (and/or/not, eq/ne/gt/gte/lt/lte/in/exists/within_seconds_of) над контекстом {operation, ledger, tariff, client, context}; scope operation|operation_pair|client_window.
2. Сид data/rules.yaml: RULE-QR-FEE-001 (refund_fee), RULE-DOUBLE-DEBIT-001 (refund_fee), RULE-PROMO-RATE-001 (propose_hitl), RULE-NOTIF-DUP-001 (suppress_duplicates) с владельцами и error_code.
3. Инструмент check_business_rules(operations, context) → rule_violation.schema.json; запись rule_evaluations с evidence и latency; версия правила — в трассировку.
4. Узел check_rules в графе после gather_context (T-059); условное ребро fast_path по результату и политикам (T-174).
5. API GET/PUT /api/rules, POST /api/rules/evaluate, GET /api/rules/evaluations; UI-вкладка /settings → Правила (JSON-редактор условия с валидацией по схеме).

## Критерии приёмки
- [ ] Все четыре правила покрыты unit-тестами на matched/not_matched и граничные случаи (комиссия 0, тариф ненулевой).
- [ ] Латентность оценки правил на окне 72 ч ≤ 300 мс (p95).
- [ ] Изменение правила увеличивает version и видно в трассировке последующих запусков.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/unit/test_rules_engine.py
python scripts/contracts_check.py
```

## Отчёт субагента
Дополнение (ветка `feat/b06-b16-abs-feed`): API `GET /api/rules`, `PUT /api/rules` (полная замена набора, `version+1` у изменённых, отсутствующие деактивируются, условие валидируется интерпретатором), `POST /api/rules/evaluate` (прогон активных правил по операции/клиенту без записи), `GET /api/rules/evaluations` (история срабатываний с итогами по правилам).
