# T-017 — Продукты клиентов и 14 дней операций

| Поле | Значение |
|---|---|
| Эпик | E2 Справочники и генераторы данных |
| Субагент | `SA-Clients` (клиенты и операции) |
| Оценка | M (1–2 дня) |
| Волна | 2 |
| Слой | `L2` Симулятор и данные (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `in_progress` |

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
Ветка `codex/T-017-operation-history`, ревизия01.11.2026. Данные генератора вынесены
в `data/op_paths.yaml`: пики10–12/18–21, веса дней/сегментов, lognormal суммы,
пути существующих систем. Failed1% имеют совместимый error_code. Отдельная модель
BRD4% ошибочной комиссии успешных QR сохраняется; refund/HITL политики не меняются.
`seed_operations` сохранён как совместимый импорт из clients.py; реализация использует
потоковый COPY, существующая история не перезаписывается. Устранены клиенты без
продуктов (ветка youth), добавлен masked_number в карточные terms. Контракты не меняются.

Замер на отдельной PostgreSQL16 `cx_operation_history`, demo5000/seed42:
Финальный demo5000/seed42 наcx_operation_demo_final:600000 операций за16.814с,
5930failed(0.9883%),102170QR/4097сошибочнойкомиссией. Полныйseedс2500signals/
400incidentsиbaseline dump16.95MB —30.2с при параллельной тестовой нагрузке.
Порог операции≤60с/весьseed≤90с выполнен на этой машине, CI timing ожидается.
Адресные15unit+3реальныеDBрегрессии —18passed; χ² по часам/дням,
распределение логарифмов сумм, интенсивность сегментов, детерминизм/границы,
masked_number/промо/идемпотентность. Финальное покрытие изменённых исполняемых строк128/145=88.28%.
Replay read-model тест переведён на immutable context записанной live кассеты
(backend/tests/fixtures/replay_bank_v1.json); исходные assertions усилены отсутствием
fallback/error steps. Изменение контекста по-прежнему даёт miss: кассета не rekeyed.
Автономный agent test выбирает заявленный segment и72h окно, текст соответствует
реальной операции; больше не зависит от произвольного старого размера138руб.
Явный failure_codes pool не создаёт PROC-QR-FEE-CHARGED без fee; этот код остаётся
только у успешного QR с ошибочной комиссией. Финальный16case unit+agent regression green.
Полный regression/lint запущен;
финальное покрытие/DoD и live GigaChat пока не заявлены.

Фиксация зависимости T-018 (02.11.2026): текущий commit — подготовленный пакет T-017, не готовый к merge. Последний полный прогон:748 unit passed/18 skipped; integration остановлен на неизменённом customer_messages gift-approval regression. Подтверждена корневая причина вне генератора: агент мог вернуть несвязанную QR-комиссию по жалобе на вклад, закрыть обращение и выдать подарок. Исправляется отдельно в codex/fix-refund-case-relevance с финансовым review; после интеграции обязателен повтор полного make test. Никакие исходные assertions этой ошибки не ослаблены. Финальные targeted18passed и benchmark600000ops16.814s/fullseed30.2s сохраняются.
