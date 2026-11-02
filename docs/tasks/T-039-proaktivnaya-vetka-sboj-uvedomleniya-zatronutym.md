# T-039 — Проактивная ветка: сбой → уведомления затронутым клиентам до жалоб

| Поле | Значение |
|---|---|
| Эпик | E3 Симулятор банка, команды, SLA |
| Субагент | `SA-Agent` (агент LangGraph) |
| Оценка | M (1–2 дня) |
| Волна | 4 |
| Слой | `L3` Агент и контуры (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | нет — можно отложить |
| Статус | `in_progress` |

## Цель
Агент реагирует на fault.started раньше клиентов (ТЗ 6 шаг 4, сценарий 6).

## Разделы ТЗ (docs/TZ.md)
§6, §8.4, §18 сц. 6

## Контракты
- `events/sim/fault.schema.json`
- `events/agent/decision.schema.json (client_action.kind=proactive_notice)`

## Зависимости
- Зависит от: [T-034](T-034-generator-sboev-i-vosstanovlenij.md), [T-056](T-056-agentstate-graf-langgraph-checkpointer-zapusk-po.md), [T-062](T-062-uzel-act-kommunikacii-klientu-i-komandam.md)
- Блокирует: [T-064](T-064-deduplikaciya-i-massovye-incidenty.md)

## Что сделать
1. Подписчик fault.started → создание «служебного» сигнала origin=proactive → граф агента: оценка массовости, создание инцидента incident_type=proactive или tech_fault, выбор затронутых клиентов (по операциям в окне), рассылка proactive_fault по согласиям, установка mass_impact.
2. Дедупликация последующих жалоб к этому инциденту (T-064).
3. Отчёт в карточке: сколько уведомлено, сколько жалоб предотвращено (по модели поведения).

## Критерии приёмки
- [ ] Сценарий 6: 120 затронутых, ≥ 90 уведомлены до первой жалобы, 30 жалоб дедуплицированы.
- [ ] Поведенческая модель фиксирует рост care_score у уведомлённых.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
make scenario ID=mass_notif
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._


### 02.11.2026: prerequisite temporal cause fix

В отдельном focused follow-up World.gen_operations проверяет реальные
fault run/system/code/time/region границы; future fault не создаёт ранний failed
link/жалобу. Порядок RNG draws сохранён, rollback/retry и actual PG positive/negative
случаи проверены: 5 passed. [Отчёт](../reviews/T-039-temporal-cause-follow-up.md).
Это не реализация всей T-039: proactive subscriber/массовый incident/предотвращённые
жалобы остаются отдельной работой; критерии приёмки не помечались выполненными.

Combined adjacent regression: 49 passed (169.73 s), changed executable line
coverage 31/31=100%; source SHA в proof JSON. Полный suite/CI остаётся за
окончательной композицией, completion T-039 этим не утверждается.

## T039 native proactive path: начальный checkpoint

Один internal service signal без личности клиента проходит обычный Mock graph и native consented fanout; actual causal/time/provenance guards и API1.5.25 default-deny внешнего service origin подготовлены. Dependency schema9/owner2PG, ingress13unit, graph/timing5PG, полный unit1787/18skip и contracts45/162 прошли. Automatic wake/recovery/late recipients, actual120/90/30, care proof, итоговые full/coverage/CI и human review ещё в работе. Prevented complaints пока null/not_modelled, не равно Sent. [Отчёт](../reviews/T-039-proactive-fault.md). Статус и критерии всей карточки не объявляются завершёнными.
