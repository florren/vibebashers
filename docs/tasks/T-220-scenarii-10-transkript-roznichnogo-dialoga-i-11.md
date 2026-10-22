# T-220 — Сценарии 10 «Транскрипт розничного диалога» и 11 «Сарказм → уточнение → эскалация»: YAML, автотесты, кассеты, блок D демо-скрипта

| Поле | Значение |
|---|---|
| Эпик | E18 Приём транскриптов, роутер-инструменты, «красные фразы», зоны карты [ДТЗ] |
| Субагент | `SA-QA` (тесты и CI) |
| Оценка | M (1–2 дня) |
| Волна | 4 |
| Слой | `L5` Качество (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `todo` |

## Цель
Оба сценария ДТЗ воспроизводимы кнопкой и в CI, с бюджетами задержек и кассетами replay (ТЗ 18, 19 п. 26–33).

## Разделы ТЗ (docs/TZ.md)
§18, §19, §16.4, §5.4

## Контракты
- `api/openapi.yaml: /api/ingest/*, /api/tickets, /api/escalations, /api/map/zones`
- `events/agent/decision_chain.schema.json`

## Зависимости
- Зависит от: [T-216](T-216-paketnyj-analiz-transkripta-pacing-batch-transcr.md), [T-213](T-213-router-instrumenty-route-to-department-notify-cu.md), [T-214](T-214-tiketnica-v-tickets-get-api-tickets-vkladka-tike.md), [T-217](T-217-ui-vkladka-transkripty-na-compliance-zagruzka-sp.md), [T-218](T-218-karta-sloj-zony-zelenaya-zheltaya-krasnaya-po-v.md), [T-209](T-209-adaptery-istochnikov-ingest-sources-rest-polling.md), [T-198](T-198-kassety-scenariev-8-9-i-avtotesty-na-nih-procedu.md)
- Блокирует: —

## Что сделать
1. data/scenarios/retail_transcript_red_phrases.yaml (ID сценария 10) и social_sarcasm_escalation.yaml (ID 11): шаги, ожидания, бюджеты; пункты в меню демонстратора (Ctrl+Shift+R).
2. Автотесты: сценарий 10 — отчёт ≤ 10 с, 3 находки, алерт immediate ≤ 2 с, сигнал клиента с problem_summary; сценарий 11 — polling → sentiment/sarcasm → request_clarification → route_to_department → escalate_to_manager → зона red → тикер → decision-chain в Markdown.
3. Кассеты replay для обоих сценариев; прогон в CI на кассетах и nightly на live.
4. Демо-скрипт: блок D (+2 мин) в docs/demo-script.md (T-204 расширить).

## Критерии приёмки
- [ ] Оба сценария зелёные на кассетах в CI и на live-провайдере вручную.
- [ ] Блок D описан пошагово с таймингом.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
make scenario ID=retail_transcript_red_phrases
make scenario ID=social_sarcasm_escalation
pytest backend/tests/scenarios/test_scenario_10_11.py
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
