# T-058 — Инструменты записи и побочных эффектов

| Поле | Значение |
|---|---|
| Эпик | E5 Агент LangGraph |
| Субагент | `SA-Agent` (агент LangGraph) |
| Оценка | L (3–4 дня) |
| Волна | 2 |
| Слой | `L3` Агент и контуры (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `todo` |

## Цель
create_incident, link_signal_to_incident, update_incident, notify_client, notify_team, create_task, schedule_followup, close_incident, compute_economics, request_human_decision, verify_service_delivered.

## Разделы ТЗ (docs/TZ.md)
§9.2, §8, §11.1

## Контракты
- `events/agent/tool_call.schema.json`
- `db/schema.sql: incidents, incident_signals, incident_status_history, notifications, tasks, followups`

## Зависимости
- Зависит от: [T-057](T-057-instrumenty-chteniya-konteksta.md), [T-014](T-014-kody-oshibok-tipy-signalov-pravila-marshrutizaci.md), [T-015](T-015-shablony-uvedomlenij-spravochnik-podarkov-stavki.md)
- Блокирует: [T-036](T-036-emulyator-komand-i-cifrovoj-sled-incidenta.md), [T-041](T-041-preryvanie-i-vozobnovlenie-emulyacii-vosstanovle.md), [T-062](T-062-uzel-act-kommunikacii-klientu-i-komandam.md), [T-078](T-078-podarki-raschet-zadachi-vydacha-posle-podtverzhd.md), [T-089](T-089-doska-i-tablica-incidentov-s-indikatorami-sla.md), [T-164](T-164-uhod-klienta-churn-events-incident-account-closu.md), [T-175](T-175-instrumenty-refund-fee-find-affected-clients-get.md), [T-176](T-176-priemnik-otzyvov-external-posts-replies-instrume.md), [T-186](T-186-schetchik-narushenij-mashina-sostoyanij-sessii-a.md), [T-207](T-207-edinaya-shema-soobscheniya-i-normalizator-ingest.md)

## Что сделать
1. Единственная точка записи для агента; каждая функция — транзакция, запись истории статусов, NOTIFY в соответствующий канал, валидация переходов статусов (конечный автомат ТЗ 8.3).
2. create_incident рассчитывает sla_due_sim/take_due_sim/report_due_sims по матрице и рабочему календарю; приоритет P1–P4 по формуле ТЗ 8.1.
3. notify_client: рендер шаблона по каналу/сегменту/языку, проверка согласий, запись notifications, доставка (Mailpit/бот/трекинг/эмуляция), событие.
4. schedule_followup/followups-воркер: пробуждение по sim_time → продолжение графа.
5. verify_service_delivered: проверка факта (операция успешна/ставка восстановлена/продукт активен) перед закрытием.

## Критерии приёмки
- [ ] Все создаваемые инструментами строки (incidents, tasks, notifications, team_actions, client_states …) получают run_id из AgentState.run_id; тест проверяет отсутствие строк без run_id после сценария.
- [ ] Недопустимый переход статуса → исключение, запись не меняется.
- [ ] Все записи агента в БД видны в db_activity_log с корреляцией к run_id.
- [ ] Тесты на каждый инструмент.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/unit/test_tools_write.py
```

## Отчёт субагента
Ветка `feat/b04-agent`. `backend/app/agent/tools/write.py`: create_incident (SLA/приоритет из decide, history new→classified→routed, incident_signals primary, problem_summary, NOTIFY incidents), link_signal_to_incident (пересчёт mass_impact, флаг mass_impact при ≥3), update_incident (FSM ТЗ 8.3 — недопустимый переход → ToolError; taken/resolved/closed_sim, sla_breached), notify_client (шаблон notification_templates по коду/каналу/сегменту с `{{ var }}`, text_override от LLM, маскирование ПДн, согласия → suppressed, дедуп по сигналу/шаблону, публичный ответ → recipient_type=public), notify_team (team_notice + соисполнители), create_task (gift/manual_review…, assignee по умолчанию team_cx), request_human_decision (human_decisions + NOTIFY hitl + needed_human), schedule_followup, escalate_to_manager (escalations + статус escalated), close_incident, set_client_state. Все — идемпотентны по agent_run_id (повторный act не дублирует). **Не сделано:** compute_economics/verify_service_delivered — отложены в B06/T-16x (economics_preview в решении есть). Время: ~50 мин.
