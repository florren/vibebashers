# T-076 — Политики HITL (policies.py) и тесты

| Поле | Значение |
|---|---|
| Эпик | E6 HITL и подарки |
| Субагент | `SA-Agent` (агент LangGraph) |
| Оценка | S (≤ 0,5 дня) |
| Волна | 2 |
| Слой | `L3` Агент и контуры (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `todo` |

## Цель
Чистые функции, определяющие, когда нужен человек (ТЗ 9.3).

## Разделы ТЗ (docs/TZ.md)
§9.3, §10

## Контракты
- `events/agent/decision.schema.json (human_reason)`

## Зависимости
- Зависит от: [T-006](T-006-sync-contracts-generaciya-enums-pydantic-shem-ts.md), [T-014](T-014-kody-oshibok-tipy-signalov-pravila-marshrutizaci.md)
- Блокирует: [T-061](T-061-uzel-decide-sla-marshrutizaciya-prioritet-politi.md), [T-174](T-174-bystryj-put-agenta-uslovnoe-rebro-act-instant-st.md), [T-213](T-213-router-instrumenty-route-to-department-notify-cu.md)

## Что сделать
1. needs_human(classification, context, policy_settings) → HumanReason|None: low_confidence (< порога), ultra_vip, legal_regulatory, fraud_amount (> 50 000 ₽), partner_privilege, repeat_3plus, classifier_conflict; настройки из settings.policies.
2. Генерация human_options и human_recommendation по причине (шаблоны).
3. Юнит-тесты на каждую ветку и комбинации.

## Критерии приёмки
- [ ] 100 % веток покрыты тестами.
- [ ] Пороги меняются через настройки без рестарта.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/unit/test_policies.py
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
