# T-161 — Параметрическая модель состояний клиента

| Поле | Значение |
|---|---|
| Эпик | E14 Поведение клиентов и калькулятор «Факт» |
| Субагент | `SA-Behavior` (поведение клиентов) |
| Оценка | L (3–4 дня) |
| Волна | 2 |
| Слой | `L2` Симулятор и данные (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `in_progress` |

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
2. Запись client_states (is_current), событий client.* и raw per-tick intent hazard. Existing clients.churn_risk и его контекстная projection сохраняются; новое probability mapping/калибровка — отдельная T-165 с provenance review.
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
Pure checkpoint в `codex/T-161-behavior-model`: типизированные переходы,
p_complain/delay/repeat через SimRng, точная формула hazard и обязательные policy
inputs без defaults. Runtime не включён; DB/DDL, параметры и финансы не менялись.
70 unit passed (52 behavior + 4 textgen + 14 baseline), Ruff/mypy green.
После initial collection gap использован разрешённый frozen SDK venv; общий
venv не менялся. Полный regression пока не выполнялся. Полные критерии T161 **не выполнены**: ожидаются решения по
policy/ADR/storage, durable integration и process-restart/full-suite proof.

Предложение и границы: [T-161 pure core / policy / storage](../reviews/T-161-pure-core-policy-storage.md).


По новому запросу пользователя подготовлено **предложение**, не активация:
[data/behavior/demo_policy.review.yaml](../../data/behavior/demo_policy.review.yaml),
[ADR-0024](../adr/ADR-0024-demo-client-behavior-policy.md) и
[sensitivity JSON](../reviews/T-161-demo-policy-sensitivity.json).
Все новые значения явно синтетические, enabled=false/approved_by=null;
исходные psychotype/segment/gift параметры и runtime не менялись.
60 pure tests passed; до wire нужны человеческий review и отдельная реализация/
проверка durable state/receipt/timer границы. T161 остаётся in_progress.


02.11.2026 пользователь явно подтвердил значения/семантику demo-policy из
`ba5145d` для реализации. Зафиксированы status=approved_for_implementation,
approved_by=user_in_chat, approved_date и values-only scope; enabled=false.
Все поведенческие значения deep-equal утверждённому packet; повторное одобрение
тех же значений не требуется. Следуют typed components/result, durable writer и
Twin reconciliation. Неполная реализация не активируется; новые контракты — после
конкретного final review. Другие денежные defaults/live Telegram не разрешались.


### 02.11.2026: durable owner, ещё без actor activation

Реализованы transactional BehaviorStore/BehaviorOwner, strict component codec,
immutable pinned policy/params, фактические notification/SLA/resolution/Twin
adapters, durable evidence/receipts/work/tick receipts. SQL — только
[review proposal](../reviews/T-161-storage-proposal.sql), не actual Alembic 0017.
Собственная scratch DB на actual 0014: 99 pure + 13 actual PG = **112 passed**,
exact-file module line coverage **90.85%**; Ruff/mypy green. Отчёт и ограничения:
[T-161 durable checkpoint](../reviews/T-161-durable-owner-checkpoint.md).

Policy значения уже одобрены; прежние требования повторного value approval выше
описывают историю checkpoints. enabled=false/неподключённый actor сохраняются.
До завершения нужны actual 0015/0016→0017 composition, единый writer с agent,
исправление временной fault причинности в World, явное churn_risk отображение,
tick/RNG adapter, OS restart/archive/baseline/full-suite proof. Новых денежных
правил, выдачи подарков, внешнего LLM/TG и production DB операций нет.


Agent writer/read-scope follow-up 83e0cf8: opt-in graph TX evidence sink, truthful
pending/actual trace, scoped legacy writer и baseline+ctx reader; 193 regression
passed, extra actual load_deps 1 passed; changed-line coverage94.59%. Runtime
не включён. [Concrete churn_risk decision proposal](../reviews/T-161-churn-risk-decision-proposal.md)
сохраняет legacy projection и предлагает явное acceptance уточнение вместо
неодобренного hazard*100; решение/калибровка не подменяются молчаливой формулой.


02.11.2026 пользователь явно одобрил variant A из9700400. Точный scope/acceptance
diff применён: raw per-15min intent hazard хранится отдельно в client_states,
legacy clients.churn_risk/projection сохраняется доT-165. Approval metadata и
source decision: [решение](../reviews/T-161-churn-risk-decision-proposal.md).
Новых probability/money defaults и hazard*100 нет; прежнее demo-policy approval
осталось неизменным. Runtime/actual0017 proof продолжается, statusin_progress.


### Runtime candidate и проверки 02.11.2026

Исторические записи выше относятся к ранним checkpoints. Текущий candidate
имеет actual0017 после0016, единый Sim tick owner, durable evidence/work/receipts,
World pending и actual native fault recovery; approved policy включена только в
тестируемой ветке для фактических free/scenario. Live остаётся вне hazard owner;
legacy churn_risk не подменён raw hazard. Production не изменялся.

Фактический полный integration на9bba1d9:469 passed/2failed/4skip,2752.16s.
Два конкретных follow-up (валидная explicit transaction при autocommit=True,
явный reload stale reader в test-only factory fixture) проверены3target+24affected
pass. [Причины и границы](../reviews/T-161-full-regression-findings.md).
Полный integration пока не назван успешным; final exact CI, актуальное coverage/
performance и конкретный human event/runtime/reset_day/financial-time review
ещё нужны. Два ранее одобренных решения demo-policy/variant A не запрашиваются
повторно. Карточка остаётся in_progress.


Frozen runtime70e4b00: full unit1725/18skip; fresh pure-core+все7behaviorPG
167passed, новый package line coverage1657/1772=93.51% (каждый модуль≥90.12%).
[Актуальный source-qualified отчёт](../reviews/T-161-full-regression-findings.md).
Known whole-World Team plan/RNG gap устраняется отдельной T037 child карточкой;
T161 отдельно не объявляет универсальную restart-equivalence. Карточки/PR не
смешиваются без atomic exception; конечная composition CI и final human review
остаются обязательными.
