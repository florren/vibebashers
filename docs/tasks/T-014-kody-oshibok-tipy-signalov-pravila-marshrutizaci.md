# T-014 — Коды ошибок, типы сигналов, правила маршрутизации, матрица SLA

| Поле | Значение |
|---|---|
| Эпик | E2 Справочники и генераторы данных |
| Субагент | `SA-Refs` (справочники) |
| Оценка | M (1–2 дня) |
| Волна | 1 |
| Слой | `L1` Базис (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `todo` |

## Цель
Словари, на которые опираются классификатор, маршрутизация и SLA.

## Разделы ТЗ (docs/TZ.md)
§7, §8.1, §8.2, §9.3

## Контракты
- `db/schema.sql: error_codes, signal_types, routing_rules, sla_matrix`
- `events/common.schema.json`

## Зависимости
- Зависит от: [T-013](T-013-produkty-sistemy-komandy-kanaly.md)
- Блокирует: [T-018](T-018-predystoriya-sboev-i-logi-sistem.md), [T-019](T-019-biblioteka-tekstov-signalov.md), [T-037](T-037-sla-dvizhok.md), [T-049](T-049-mock-provajder-pravila-shablony-determinizm.md), [T-058](T-058-instrumenty-zapisi-i-pobochnyh-effektov.md), [T-076](T-076-politiki-hitl-policies-py-i-testy.md)

## Что сделать
1. data/error_codes.yaml: ≥ 25 кодов по системам/продуктам (DEP-TIMEOUT-503, PROMO-RATE-MISMATCH, PROC-DOUBLE-DEBIT, NOTIF-DELAY, APP-LOGIN-FAIL, CARD-ISSUE-STUCK, LIMIT-CALC-ERR, ANTIFRAUD-FALSE-BLOCK …) с default complexity/criticality и описанием.
2. signal_types по ТЗ 7 с base_criticality, requires_hitl, creates_incident.
3. routing_rules: ≥ 15 правил (тип+продукт+система → команды), приоритеты; правило по умолчанию → team_cx.
4. sla_matrix: easy 1/2/3, medium 3/4/5, hard 5/5(+отчёт д3)/10(+отчёты д3,6,9); take_hours по критичности 8/4/2.

## Критерии приёмки
- [ ] Матрица SLA в точности как ТЗ 8.2.
- [ ] Для каждого error_code есть правило маршрутизации, ведущее в команду, владеющую системой.
- [ ] Загрузка идемпотентна.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/unit/test_refs_routing.py
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
