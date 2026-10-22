# T-174 — Быстрый путь агента: условное ребро, act_instant, structured output instant_decision

| Поле | Значение |
|---|---|
| Эпик | E15 Внешние площадки и автономный возврат [BRD] |
| Субагент | `SA-Agent` (агент LangGraph) |
| Оценка | L (3–4 дня) |
| Волна | 3 |
| Слой | `L3` Агент и контуры (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `todo` |

## Цель
Цепочка «пост → возврат → публичный ответ» ≤ 10 с (p50) при подтверждённом правиле и разрешающих политиках (ТЗ 6 п. 7a, 8.1 instant, 16.4, 21.4).

## Разделы ТЗ (docs/TZ.md)
§6, §8.1, §8.2, §9.1, §9.3, §16.4, §21.4

## Контракты
- `events/agent/instant_decision.schema.json`
- `events/agent/decision.schema.json (fast_path, rule_codes)`
- `db/schema.sql: incidents.complexity = instant, incident_type = fee_refund`

## Зависимости
- Зависит от: [T-172](T-172-rules-engine-business-rules-dsl-uslovij-uzel-che.md), [T-173](T-173-matching-klienta-po-kosvennym-dannym-match-clien.md), [T-060](T-060-uzel-classify-i-prompty-v1.md), [T-061](T-061-uzel-decide-sla-marshrutizaciya-prioritet-politi.md), [T-062](T-062-uzel-act-kommunikacii-klientu-i-komandam.md), [T-076](T-076-politiki-hitl-policies-py-i-testy.md)
- Блокирует: [T-179](T-179-scenarij-8-komissiya-za-qr-oplatu-i-publichnyj-o.md), [T-196](T-196-avtomaticheskij-failover-po-tajmautu-i-oshibkam.md), [T-198](T-198-kassety-scenariev-8-9-i-avtotesty-na-nih-procedu.md)

## Что сделать
1. policies.py: fast_path_allowed(violations, match, classification_hint, client) по 9.3 — лимит refund_autonomy_limit_rub (5 000 / 15 000 premium+ / ultra_vip → HITL), уверенность ≥ 0,8/0,75, идемпотентность, refunds_30d < 3, не массовый.
2. Один вызов основной модели (Ultra, streaming, параллельные function calls) со схемой instant_decision: классификация + решение + public_reply_ru + client_notice_ru + gift; промпт prompts/v1/instant_decision.md.
3. Узел act_instant: порядок «деньги → инцидент (fee_refund, resolved) → публичный ответ → личное уведомление»; verify (баланс восстановлен) → close → gift; шаги пишутся в agent_steps как обычно (один граф на экране «Под капотом»).
4. Таймаут LLM-шага 8 с → автоматический failover replay → mock без разрыва цепочки (T-196); бюджет по шагам в трассировке.
5. Если правило не подтверждено — обычный граф; если сумма выше лимита — request_human_decision с готовым предложением.
6. Замер p50/p95 на 10 прогонах сценария 8 в тесте с реальным GigaChat (маркер live) и на кассете.

## Критерии приёмки
- [ ] Сценарий 8 на кассете: цепочка ≤ 10 с, все шаги в трассировке, инцидент fee_refund закрыт, проводка refund создана один раз.
- [ ] Политики покрыты unit-тестами на каждую ветку; повторный пост не создаёт второго возврата.
- [ ] На реальном GigaChat-3-Ultra p50 ≤ 10 с, p95 ≤ 15 с (10 прогонов, отчёт в PR).
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/scenarios/test_scenario_08_qr_fee.py
pytest -m live backend/tests/scenarios/test_scenario_08_latency.py
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
