# T-061 — Узел decide: SLA, маршрутизация, приоритет, политики, проверка формулировок

| Поле | Значение |
|---|---|
| Эпик | E5 Агент LangGraph |
| Субагент | `SA-Agent` (агент LangGraph) |
| Оценка | L (3–4 дня) |
| Волна | 3 |
| Слой | `L3` Агент и контуры (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `done` |

## Цель
План действий по схеме decision: создать/связать инцидент, команда, SLA, подарок, followup, HITL.

## Разделы ТЗ (docs/TZ.md)
§8.1, §8.2, §9.3, §9.4, §8.5

## Контракты
- `events/agent/decision.schema.json`

## Зависимости
- Зависит от: [T-060](T-060-uzel-classify-i-prompty-v1.md), [T-076](T-076-politiki-hitl-policies-py-i-testy.md)
- Блокирует: [T-062](T-062-uzel-act-kommunikacii-klientu-i-komandam.md), [T-064](T-064-deduplikaciya-i-massovye-incidenty.md), [T-066](T-066-versionirovanie-promptov-i-gate-na-lite-benchmar.md), [T-077](T-077-uzel-wait-human-ochered-hitl-i-vozvrat-resheniya.md), [T-078](T-078-podarki-raschet-zadachi-vydacha-posle-podtverzhd.md), [T-174](T-174-bystryj-put-agenta-uslovnoe-rebro-act-instant-st.md), [T-213](T-213-router-instrumenty-route-to-department-notify-cu.md)

## Что сделать
1. prompts/v1/decide.md с матрицей SLA, правилами маршрутизации (как подсказкой), политиками подарков и HITL; модель предлагает, код проверяет и при необходимости корректирует (детерминированные поля — SLA, приоритет — считаются кодом и записываются в decision).
2. policy_checks заполняются результатами policies.needs_human и forbidden_phrases.
3. Для соцсетей — client_action.kind=public_reply_and_dm.
4. Экономика предпросмотра через compute_economics.

## Критерии приёмки
- [ ] На golden маршрутизация совпадает с gold ≥ 0.9 (Ultra).
- [ ] Любое решение с привилегией партнёра имеет needs_human=true.
- [ ] Все decision валидны по схеме, включая условные правила.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/unit/test_node_decide.py
```

## Отчёт субагента
Ветка `feat/b04-agent`. Узел decide: LLM даёт тексты (title_ru, text_ru, team_notice_ru, rationale_ru), код — все детерминированные поля: `sla.py` (effective_criticality с учётом флагов/сегмента/массовости, priority P1–P4, sla_for по sla_matrix и рабочим дням/часам `app.sim.clock`, complexity_for, pick_gift 300/600/1000 +200 за повтор), маршрут по routing_rules (первое совпадение по priority, ключи signal_type/error_code/system/product/channel/incident_type), incident_action create/link_existing (дедуп по error_code в окне)/none (gratitude/suggestion/info_request), политики HITL/эскалации/уточнения (`policies.py`), запрещённые формулировки → fallback на шаблон, policy_checks. Решение валидируется по `agent/decision`, пишется в signals.decision. fee_refund + easy при подтверждённом правиле. Время: ~1 ч.
