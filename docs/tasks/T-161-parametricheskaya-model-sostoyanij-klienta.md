# T-161 — Параметрическая модель состояний клиента

| Поле | Значение |
|---|---|
| Эпик | E14 Поведение клиентов и калькулятор «Факт» |
| Субагент | `SA-Behavior` (поведение клиентов) |
| Оценка | L (3–4 дня) |
| Волна | 2 |
| Слой | `L2` Симулятор и данные (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `todo` |

## Цель
Машина состояний ТЗ 4.5 для всех клиентов: переходы по событиям и таймерам, care_score, hazard.

## Разделы ТЗ (docs/TZ.md)
§4.5, §4.2

## Контракты
- `events/behavior/client_event.schema.json`
- `events/behavior/psychotype_params.schema.json`
- `db/schema.sql: client_states`

## Зависимости
- Зависит от: [T-012](T-012-segmenty-psihotipy-doli-psihotipov-po-segmentam.md), [T-032](T-032-shina-sobytij-simulyatora.md), [T-031](T-031-simclock-sim-state-i-upravlenie-simulyaciej.md)
- Блокирует: [T-020](T-020-predystoriya-signalov-incidentov-statusov-artefa.md), [T-038](T-038-dvizhok-scenariev-yaml-i-7-demo-scenariev.md), [T-091](T-091-klient-360.md), [T-132](T-132-api-svodnoj-ekonomiki-i-metrik-dashborda.md), [T-162](T-162-detekciya-snizheniya-aktivnosti-molchalivyj-uhod.md), [T-163](T-163-llm-dvojniki-podsvechennyh-klientov.md), [T-164](T-164-uhod-klienta-churn-events-incident-account-closu.md), [T-165](T-165-kalibrovka-koefficientov-uderzhaniya-po-faktam-s.md), [T-167](T-167-statisticheskie-testy-modeli-povedeniya.md)

## Что сделать
1. app/sim/behavior/model.py: обработчики op.failed/fault.started (affected), таймер жалобы по complain_delay → создание сигнала (текст из библиотеки T-019 по психотипу/тону) или silent_decline; реакции на notifications (agent_reply/proactive/progress/gift) → care_score по care_weights; повтор/эскалация по repeat_prob/escalation_prob; на каждом sla.tick для waiting/churn_intent розыгрыш hazard по формуле ТЗ 4.5; retained при закрытии с care_score ≥ порога.
2. Запись client_states (is_current), событий client.*, обновление clients.churn_risk.
3. Все вероятности через rng.py; параметры из psychotypes.params и settings.

## Критерии приёмки
- [ ] Тест на 1 000 синтетических клиентов: доля жалоб по психотипам в пределах ±3 п. п. от p_complain; silent_churner жалуется ≤ 15 %.
- [ ] care_score растёт при проактивном уведомлении и падает при нарушении SLA (тесты).
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/unit/test_behavior_model.py
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
