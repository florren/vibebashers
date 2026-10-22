# T-186 — Счётчик нарушений, машина состояний сессии, алерт и инцидент misselling

| Поле | Значение |
|---|---|
| Эпик | E16 Аудиомониторинг отделения и мисселлинг [BRD] |
| Субагент | `SA-Compliance` (аудиосессии, детектор мисселлинга, алерты [BRD]) |
| Оценка | M (1–2 дня) |
| Волна | 3 |
| Слой | `L3` Агент и контуры (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `todo` |

## Цель
Порог X ≥ 3 → немедленный алерт руководителю (WebSocket, опционально Telegram) и инцидент misselling в team_compliance с HITL (ТЗ 22.5–22.6, 8.1).

## Разделы ТЗ (docs/TZ.md)
§8.1, §22.5, §22.6, §9.3

## Контракты
- `db/schema.sql: compliance_alerts, incidents (misselling)`
- `api/openapi.yaml: compliance/alerts*, triggers/{id}`
- `events/compliance/session_event.schema.json`

## Зависимости
- Зависит от: [T-185](T-185-llm-detektor-missellinga-lightning-podtverzhdeni.md), [T-058](T-058-instrumenty-zapisi-i-pobochnyh-effektov.md), [T-077](T-077-uzel-wait-human-ochered-hitl-i-vozvrat-resheniya.md), [T-131](T-131-raschet-ekonomiki-dcltv-po-incidentu.md)
- Блокирует: [T-187](T-187-ekran-compliance-split-screen-transkribacii-sche.md), [T-188](T-188-ekran-manager-emulyator-plansheta-i-smart-chasov.md), [T-189](T-189-alert-o-missellinge-v-telegram-rukovoditelyu.md), [T-192](T-192-scenarij-9-misselling-v-otdelenii-yaml-avtotest.md), [T-202](T-202-ekonomika-fee-refund-i-misselling-stroka-effekta.md), [T-216](T-216-paketnyj-analiz-transkripta-pacing-batch-transcr.md)

## Что сделать
1. Состояния live → alerted → closed; trigger_count по confirmed; dismissed уменьшает счётчик; алерт однократный за сессию; порог alert_threshold из сессии/настроек.
2. compliance.alert ≤ 1 с после порога: WebSocket compliance + Telegram (T-189) при заданном manager_chat_id; создание инцидента misselling (created_by=compliance, team_compliance, criticality high, medium complexity) с цитатами и рекомендацией через инструменты агента; постановка в HITL руководителя (go/false_positive/open_incident).
3. POST /alerts/{id}/ack → human_decisions; go → инцидент in_progress + пометка сделки «приостановлена» в Клиент 360; false_positive → триггеры dismissed, инцидент rejected, примеры в обучающую выборку; разъяснение клиенту (шаблон misselling_clarification) — только после решения человека.
4. Экономика: misselling_case_cost_rub из economics_settings; предотвращённым считается случай с реакцией go до закрытия сделки (T-202).

## Критерии приёмки
- [ ] Третья подтверждённая фраза → alerted, алерт в WebSocket ≤ 1 с, инцидент misselling в очереди HITL.
- [ ] Повторные триггеры после алерта не создают второго алерта; dismissed уменьшает счётчик.
- [ ] Все переходы покрыты unit-тестами машины состояний.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/unit/test_compliance_state.py backend/tests/integration/test_compliance_alerts.py
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
