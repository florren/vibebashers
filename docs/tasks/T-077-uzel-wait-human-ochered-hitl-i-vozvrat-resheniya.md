# T-077 — Узел wait_human, очередь HITL и возврат решения в граф

| Поле | Значение |
|---|---|
| Эпик | E6 HITL и подарки |
| Субагент | `SA-Agent` (агент LangGraph) |
| Оценка | M (1–2 дня) |
| Волна | 3 |
| Слой | `L3` Агент и контуры (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `todo` |

## Цель
Interrupt графа, карточка решения, продолжение с учётом выбора человека; решения становятся few-shot.

## Разделы ТЗ (docs/TZ.md)
§10, §12.2 экран 2 (Требует решения)

## Контракты
- `api/openapi.yaml: hitl/*`
- `db/schema.sql: human_decisions`

## Зависимости
- Зависит от: [T-056](T-056-agentstate-graf-langgraph-checkpointer-zapusk-po.md), [T-061](T-061-uzel-decide-sla-marshrutizaciya-prioritet-politi.md), [T-008](T-008-realtime-listen-notify-websocket-hab.md)
- Блокирует: [T-078](T-078-podarki-raschet-zadachi-vydacha-posle-podtverzhd.md), [T-079](T-079-ui-ocheredi-hitl-i-kartochki-resheniya.md), [T-175](T-175-instrumenty-refund-fee-find-affected-clients-get.md), [T-186](T-186-schetchik-narushenij-mashina-sostoyanij-sessii-a.md)

## Что сделать
1. wait_human: запись human_decisions (предложение, варианты, рекомендация, контекст), статус сигнала/инцидента awaiting_human, публикация hitl/requested, interrupt.
2. POST /api/hitl/{id}: accept/modify/reject/delegate → запись решения, резюме графа с изменённым decision; таймаут ожидания (настройка, по умолчанию 2 сим-часа) → эскалация cx_lead, при отсутствии — безопасное действие по умолчанию (acknowledge клиенту, инцидент без подарка).
3. use_as_fewshot → доступно узлу classify/decide.

## Критерии приёмки
- [ ] Сценарий 1 (VIP): появляется в очереди с 3 вариантами; выбор «изменить подарок» отражается в задаче и уведомлении.
- [ ] После рестарта приложения ожидающие решения не теряются.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/integration/test_hitl.py
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
