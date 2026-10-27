# T-224 — Сборщик следа app/trace: каузальный обход, фазы до/объект/после, итог, ожидаемые шаги, свёртка веера; GET /api/trace

| Поле | Значение |
|---|---|
| Эпик | E22 Сквозная демонстрация «Путь обращения» [АРХ] |
| Субагент | `SA-Trace` (модель следа, поиск, путь обращения [АРХ]) |
| Оценка | L (3–4 дня) |
| Волна | 8 |
| Слой | `L3` Агент и контуры (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `todo` |

## Цель
Единая серверная модель следа (ТЗ 28.3–28.4): для любого объекта цепочки собрать события «до», «после», итог и ожидаемые шаги детерминированно, быстро и только на чтение.

## Разделы ТЗ (docs/TZ.md)
§28.3, §28.4, §28.7, §27.5, §9.7

## Контракты
- `events/trace/*`
- `api/openapi.yaml: GET /api/trace/{kind}/{ref}`
- `events/agent/decision_chain.schema.json (ссылка из события)`

## Зависимости
- Зависит от: [T-223](T-223-kontrakty-sleda-i-poiska-migraciya-0004-openapi.md), [T-213](T-213-router-instrumenty-route-to-department-notify-cu.md), [T-214](T-214-tiketnica-v-tickets-get-api-tickets-vkladka-tike.md), [T-186](T-186-schetchik-narushenij-mashina-sostoyanij-sessii-a.md), [T-216](T-216-paketnyj-analiz-transkripta-pacing-batch-transcr.md), [T-176](T-176-priemnik-otzyvov-external-posts-replies-instrume.md)
- Блокирует: [T-225](T-225-model-put-obrascheniya-stadii-dorozhka-klienta-i.md), [T-232](T-232-ekran-sled-trace-kind-ref-do-obekt-posle-itog-oz.md)

## Что сделать
1. `backend/app/trace/relations.py`: матрица ТЗ 28.4 как данные — для каждого `kind` список связей-предшественников и последователей с SQL по индексированным ключам (сигнал ← ingest_messages/external_posts/transcripts/audio_sessions/csi_responses/операция/сбой/комиссия/`parent_signal_id`; сигнал → agent_runs/agent_steps/tool_calls → rule_evaluations → human_decisions → escalations → incidents; инцидент → team_actions/status_history/artifacts/tasks/notifications/followups/economics/churn/client_reactions).
2. `assembler.py`: обход графа с потолками (`settings.trace`: «до» 3 звена и 40 событий, «после» до итога и 200), защита от циклов, фаза по причинности, затем по времени (`order_warning`), сигналы инцидента — «до» при привязке до создания и «после» (группой) позже.
3. Итог по виду объекта (`terminal`) и ожидаемые шаги `pending[]` из открытых `human_decisions`, запланированных `followups`, `sla_due_sim`, открытых `tasks`; свёртка веера в `TraceGroup` по порогу `fanout_threshold`.
4. Проекции событий: заголовок и описание бизнес-языком из словаря i18n, ключевые факты, бейдж источника (`live|replay|mock` из шага агента), сумма для проводок, ссылки на шаг агента; маскирование ПДн (телефон, карта, ник), без сырых промптов и ответов LLM.
5. Объекты-сущности (клиент, отделение, сотрудник, правило, код ошибки): хроника с подвижным «моментом»; режимы `run_id=current|all|<id>`; роутер `backend/app/api/trace.py`.
6. Тесты: сценарии 1, 6, 8, 9, 10, 11 на кассетах (проверка «до/после/итог»), веерный инцидент из 120 сигналов (группы, а не 120 событий), открытый HITL (пунктирный шаг), нагрузочный тест p95 ≤ 300 мс на профиле demo, тест «только чтение» (транзакция READ ONLY, LLM не вызывается).

## Критерии приёмки
- [ ] Для сигнала и инцидента сценариев 1, 8, 11 ответ содержит «до», «после» и итог; при незакрытом объекте — `terminal.reached = false` и `pending[]`.
- [ ] p95 ≤ 300 мс при следе до 200 событий (профиль demo); число SQL-запросов на след ≤ 20 (проверяется тестом).
- [ ] Ни в одном событии нет сырых ПДн, промптов и секретов; запись в БД и вызов LLM невозможны.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/integration/test_trace.py backend/tests/unit/test_trace_relations.py
curl -s 'localhost:8000/api/trace/incident/INC-000001' | jq '.stats'
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
