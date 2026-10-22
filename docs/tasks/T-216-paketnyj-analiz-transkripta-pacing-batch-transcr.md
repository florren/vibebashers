# T-216 — Пакетный анализ транскрипта (pacing=batch): transcript_report, рекомендации руководителю, алерты immediate, отправка на /manager и в лог

| Поле | Значение |
|---|---|
| Эпик | E18 Приём транскриптов, роутер-инструменты, «красные фразы», зоны карты [ДТЗ] |
| Субагент | `SA-Compliance` (аудиосессии, детектор мисселлинга, алерты [BRD]) |
| Оценка | M (1–2 дня) |
| Волна | 3 |
| Слой | `L3` Агент и контуры (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `done` |

## Цель
Готовый транскрипт анализируется целиком ≤ 10 с и даёт отчёт с цитатами и рекомендациями, который уходит руководителю на дашборд и в лог (ДТЗ FR-4.1, FR-4.3; ТЗ 22.8–22.9, критерий 32).

## Разделы ТЗ (docs/TZ.md)
§22.8, §22.9, §16.4, §19

## Контракты
- `events/compliance/transcript_report.schema.json`
- `events/compliance/session_event.schema.json: pacing, compliance.report_ready`
- `db/schema.sql: audio_sessions.pacing/report, compliance_alerts.kind/recommendation_ru/transcript_id`
- `api/openapi.yaml: /api/compliance/transcripts/{id}/report|send`

## Зависимости
- Зависит от: [T-208](T-208-priem-transkriptov-json-txt-parsery-post-api-ing.md), [T-215](T-215-taksonomiya-krasnyh-fraz-semejstvo-conduct-ruden.md), [T-186](T-186-schetchik-narushenij-mashina-sostoyanij-sessii-a.md)
- Блокирует: [T-217](T-217-ui-vkladka-transkripty-na-compliance-zagruzka-sp.md), [T-220](T-220-scenarii-10-transkript-roznichnogo-dialoga-i-11.md)

## Что сделать
1. Режим batch в машине состояний сессии: utterances из transcript.turns, один проход rule-детектора по всем репликам сотрудника, затем один вызов LLM на транскрипт (контекст: реплики клиента, продукт сделки, скрипт, факты) → transcript_report; при ошибке LLM — отчёт только по правилам с пометкой.
2. Из findings создаются compliance_triggers (с recommendation_ru, fact_check) и алерты по политикам: immediate → compliance_alerts(kind=immediate) немедленно; counter — по порогу; report — только в отчёт; событие compliance.report_ready.
3. GET …/report (JSON/Markdown), POST …/send: карточка на /manager, запись notifications (лог), опционально Telegram (T-189), attach_to_incident → инцидент misselling/service_quality в team_branch_network.
4. Бюджет: ≤ 10 с p50 на 60 реплик (замер в тесте с mock и с кассетой).
5. Кассета replay для сценария 10 (T-198 расширить).

## Критерии приёмки
- [ ] Сценарий 10: отчёт с тремя находками, алерт immediate с цитатой и рекомендацией на /manager и в логе ≤ 2 с после анализа.
- [ ] Отчёт в Markdown открывается и содержит план отработки.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/integration/test_transcript_batch.py
make scenario ID=retail_transcript_red_phrases
```

## Отчёт субагента
- `backend/app/compliance/transcripts.py::analyze_transcript`: employee_quality → сессия/триггеры/алерты/отчёт `transcript_report` (находки с цитатами и факт-чеком, `script_compliance`, `overall_ru`, `action_plan_ru`), для контакт-центра без отделения — отчёт без сессии; client_signal → сигнал агенту (origin=transcript) только если клиент жалуется; статусы received→analyzing→done/failed, событие `ingest.transcript_analyzed`. API `GET /api/compliance/transcripts/{id}/report` (json|md), `POST …/send` (notifications + алерт kind=report на /manager). Pacing realtime = задержка между репликами.
