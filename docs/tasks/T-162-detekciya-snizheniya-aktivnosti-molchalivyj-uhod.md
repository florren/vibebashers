# T-162 — Детекция снижения активности («молчаливый уход») и сигнал агенту

| Поле | Значение |
|---|---|
| Эпик | E14 Поведение клиентов и калькулятор «Факт» |
| Субагент | `SA-Behavior` (поведение клиентов) |
| Оценка | M (1–2 дня) |
| Волна | 3 |
| Слой | `L2` Симулятор и данные (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `todo` |

## Цель
Агент замечает клиентов, которые не жалуются, но перестают пользоваться продуктом после сбоя.

## Разделы ТЗ (docs/TZ.md)
§4.5, §18 сц. 7, §9.2 (detect_activity_drop)

## Контракты
- `events/behavior/client_event.schema.json (client.activity_drop)`
- `events/agent/tool_call.schema.json`

## Зависимости
- Зависит от: [T-161](T-161-parametricheskaya-model-sostoyanij-klienta.md), [T-033](T-033-generator-operacij-v-realnom-vremeni.md), [T-056](T-056-agentstate-graf-langgraph-checkpointer-zapusk-po.md)
- Блокирует: [T-167](T-167-statisticheskie-testy-modeli-povedeniya.md)

## Что сделать
1. Модель поведения снижает интенсивность операций клиента в состоянии affected/silent (множитель 0.2–0.5); детектор раз в сим-час сравнивает активность за 48 ч с baseline для клиентов, затронутых сбоями за 7 дней → client.activity_drop → служебный сигнал origin=proactive типа churn для агента.
2. Инструмент detect_activity_drop для ручного/графового запроса.
3. Агент отвечает проактивным уведомлением с объяснением и баллами (решение через decide).

## Критерии приёмки
- [ ] Сценарий 7: silent_churner обнаружен ≤ 2 сим-дней после сбоя и возвращён в satisfied после уведомления (на mock и Ultra).
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
make scenario ID=silent_churn_regression
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
