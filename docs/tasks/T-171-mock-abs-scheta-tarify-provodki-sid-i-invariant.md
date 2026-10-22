# T-171 — Mock-АБС: счета, тарифы, проводки, сид и инвариант баланса

| Поле | Значение |
|---|---|
| Эпик | E15 Внешние площадки и автономный возврат [BRD] |
| Субагент | `SA-ABS` (Mock-АБС и бизнес-правила [BRD]) |
| Оценка | L (3–4 дня) |
| Волна | 2 |
| Слой | `L2` Симулятор и данные (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `todo` |

## Цель
Stateful-эмуляция core_abs/processing по ТЗ 3.4: у каждого клиента есть счета и проводки, комиссии — отдельной строкой, баланс сходится с проводками; 3–5 % QR-операций с ошибочной комиссией PROC-QR-FEE-CHARGED как триггер сценария 8.

## Разделы ТЗ (docs/TZ.md)
§3.4, §13, §15 (SA-ABS), §21.4

## Контракты
- `db/schema.sql: accounts, tariffs, ledger_entries, operations.method/fee_amount`
- `events/sim/abs.schema.json`
- `api/openapi.yaml: abs/*`

## Зависимости
- Зависит от: [T-005](T-005-primenenie-schema-sql-sqlalchemy-modeli-sessii.md), [T-017](T-017-produkty-klientov-i-14-dnej-operacij.md), [T-040](T-040-servis-zapuskov-emulyacii-sim-runs-run-id-rezhim.md)
- Блокирует: [T-172](T-172-rules-engine-business-rules-dsl-uslovij-uzel-che.md), [T-173](T-173-matching-klienta-po-kosvennym-dannym-match-clien.md), [T-175](T-175-instrumenty-refund-fee-find-affected-clients-get.md), [T-176](T-176-priemnik-otzyvov-external-posts-replies-instrume.md), [T-202](T-202-ekonomika-fee-refund-i-misselling-stroka-effekta.md)

## Что сделать
1. app/abs/service.py: open_account, post_entry(kind, amount, correlation_id) с идемпотентностью по correlation_id, баланс обновляется в одной транзакции; события abs.* в шину (envelope) и топик WebSocket abs.
2. Генератор операций (T-017/T-033) дополняется method (qr_sbp/card/transfer/cash/online), merchant из вымышленного списка, fee по tariffs; тарифы: QR/СБП для физлиц — 0 ₽; дефекты PROC-QR-FEE-CHARGED и PROC-DOUBLE-DEBIT согласованы со сбоями processing (T-018/T-034).
3. Сид: счета для всех клиентов профиля, проводки за 14 дней, card_last4 у карточных продуктов, social_handles у 60 % клиентов; снимок baseline включает Mock-АБС (T-040).
4. API: GET /api/abs/accounts/{client_id}, GET /api/abs/ledger, POST /api/abs/refunds (HITL, пакетно, прогресс в WebSocket abs).
5. Тест-инвариант: для каждого счёта balance = Σ credit + Σ refund − Σ debit − Σ fee − Σ reversal; восстановление baseline возвращает баланс клиента сценария 8 к состоянию «комиссия списана».

## Критерии приёмки
- [ ] Инвариант баланса зелёный на профиле demo.
- [ ] В demo-профиле ≥ 150 операций с ошибочной комиссией QR, распределённых по регионам и дням.
- [ ] Повторный POST /api/abs/refunds с тем же correlation_id не создаёт второй проводки.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/unit/test_abs_ledger.py backend/tests/integration/test_abs_api.py
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
