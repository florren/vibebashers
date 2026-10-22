# T-018 — Предыстория сбоев и логи систем

| Поле | Значение |
|---|---|
| Эпик | E2 Справочники и генераторы данных |
| Субагент | `SA-Logs` (сбои и логи) |
| Оценка | M (1–2 дня) |
| Волна | 2 |
| Слой | `L2` Симулятор и данные (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `todo` |

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
- [ ] Каждая failed-операция во время сбоя ссылается на fault_id.
- [ ] По любому сбою get_system_logs возвращает ≥ 3 ERROR-записи в окне.
- [ ] Валидация событий по схемам проходит.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
python scripts/seed/faults.py --profile lite --check
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
