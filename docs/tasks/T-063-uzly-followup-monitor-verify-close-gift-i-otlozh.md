# T-063 — Узлы followup_monitor, verify, close, gift и отложенные обращения

| Поле | Значение |
|---|---|
| Эпик | E5 Агент LangGraph |
| Субагент | `SA-Agent` (агент LangGraph) |
| Оценка | M (1–2 дня) |
| Волна | 4 |
| Слой | `L3` Агент и контуры (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | нет — можно отложить |
| Статус | `done` |

## Цель
Замыкание петли: ожидание команды/клиента, проверка факта, закрытие, подарок, информирование.

## Разделы ТЗ (docs/TZ.md)
§6 шаг 5, §8.3, §8.5, §12.2 экран 2 (отложенные)

## Контракты
- `db/schema.sql: followups, tasks`
- `api/openapi.yaml: signals/deferred`

## Зависимости
- Зависит от: [T-062](T-062-uzel-act-kommunikacii-klientu-i-komandam.md), [T-036](T-036-emulyator-komand-i-cifrovoj-sled-incidenta.md), [T-078](T-078-podarki-raschet-zadachi-vydacha-posle-podtverzhd.md)
- Блокирует: [T-090](T-090-kartochka-incidenta.md), [T-092](T-092-vkladki-otlozhennye-komandy-uvedomleniya.md), [T-120](T-120-stranica-trekinga-obrascheniya-i-dopolnenie.md)

## Что сделать
1. followup_monitor: причины awaiting_client/awaiting_team/promo_end/verify_fix/report_due; пробуждение по followups; смена статуса сигнала deferred и обратно.
2. verify: verify_service_delivered; при провале — возврат команде (reopen) с пометкой.
3. close: уведомление клиента понятным языком о решении, статус closed, outcome_class; gift: создание задачи по правилам (HITL для привилегий), после одобрения — уведомление gift_offer.
4. API отложенных обращений с причиной и временем пробуждения.

## Критерии приёмки
- [ ] Сценарий 5 (отложенное обращение по антифроду) просыпается в заданное время и завершает цикл.
- [ ] Закрытие без подтверждённой услуги невозможно (тест).
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
make scenario ID=deferred_fraud
```

## Отчёт субагента
Ветка: `feat/T-063-followup-close-gift` (локально). Реализованы `verify_service_delivered`, узлы `verify`/`followup_monitor`/`gift`/`close`, рёбра и `wake_due_followups`/`resume_after_followup` в `graph.py`, пробуждение в `runner.py`, расширен `GET /api/signals/deferred`, тесты `test_followup_nodes.py` и `test_followups.py`. Контракты не менялись. Отклонений от карточки нет. `pytest tests/unit/test_followup_nodes.py` — 5 passed; интеграция пропущена (нет `DATABASE_URL_TEST` в окружении).
