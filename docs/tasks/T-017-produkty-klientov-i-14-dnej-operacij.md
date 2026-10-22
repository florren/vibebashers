# T-017 — Продукты клиентов и 14 дней операций

| Поле | Значение |
|---|---|
| Эпик | E2 Справочники и генераторы данных |
| Субагент | `SA-Clients` (клиенты и операции) |
| Оценка | M (1–2 дня) |
| Волна | 2 |
| Слой | `L2` Симулятор и данные (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `todo` |

## Цель
Реалистичная предыстория операций с путями по системам — основа для связывания жалоб с логами.

## Разделы ТЗ (docs/TZ.md)
§4.1, §4.2, §4.4

## Контракты
- `db/schema.sql: client_products, operations`
- `events/sim/op.schema.json`

## Зависимости
- Зависит от: [T-016](T-016-generator-klientov-profili-lite-demo-stress.md), [T-013](T-013-produkty-sistemy-komandy-kanaly.md)
- Блокирует: [T-018](T-018-predystoriya-sboev-i-logi-sistem.md), [T-022](T-022-testy-dannyh-no-pii-pokrytie-idempotentnost-proi.md), [T-033](T-033-generator-operacij-v-realnom-vremeni.md), [T-171](T-171-mock-abs-scheta-tarify-provodki-sid-i-invariant.md)

## Что сделать
1. Продукты: 1–4 на клиента по сегменту (вклад/дебетовая/кредит/кредитка), статусы, термы с masked_number, промо-коды для части вкладов.
2. Операции: интенсивности по часам (пики 10–12 и 18–21), по дням недели, по сегментам; op_type и system_path из конфигурации data/op_paths.yaml; суммы по логнормальному распределению.
3. 14 сим-дней до текущего sim_time; ~1 % операций failed с error_code (связываются со сбоями в T-018).
4. Производительность: demo ≈ 500–700 тыс. операций ≤ 60 с (COPY).

## Критерии приёмки
- [ ] Распределение по часам соответствует конфигурации (тест χ²).
- [ ] Все system_path состоят из существующих систем; failed-операции имеют error_code.
- [ ] Время генерации в норме.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
python scripts/seed/operations.py --profile lite --check
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
