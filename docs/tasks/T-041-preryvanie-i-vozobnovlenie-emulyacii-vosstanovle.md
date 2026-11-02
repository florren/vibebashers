# T-041 — Прерывание и возобновление эмуляции: восстановление после рестарта

| Поле | Значение |
|---|---|
| Эпик | E3 Симулятор банка, команды, SLA |
| Субагент | `SA-Agent` (агент LangGraph) |
| Оценка | M (1–2 дня) |
| Волна | 3 |
| Слой | `L3` Агент и контуры (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `in_progress` |

## Цель
Эмуляцию можно прервать (Стоп, падение, остановка контейнера) и продолжить с того же сим-момента (ТЗ 4.6, 19 п. 17).

## Разделы ТЗ (docs/TZ.md)
§4.6, §9.1 (checkpointer), §8.4 (followups)

## Контракты
- `api/openapi.yaml: sim/control (resume), sim/runs/{id}/resume`
- `db/schema.sql: sim_state.rng_state/last_tick_at, followups, agent_runs.status`
- `events/ws/message.schema.json (runs: interrupted|resumed)`

## Зависимости
- Зависит от: [T-031](T-031-simclock-sim-state-i-upravlenie-simulyaciej.md), [T-040](T-040-servis-zapuskov-emulyacii-sim-runs-run-id-rezhim.md), [T-056](T-056-agentstate-graf-langgraph-checkpointer-zapusk-po.md), [T-058](T-058-instrumenty-zapisi-i-pobochnyh-effektov.md)
- Блокирует: [T-094](T-094-vkladka-zapuski-istoriya-sravnenie-sbros-k-basel.md), [T-146](T-146-testy-izolyacii-zapuskov-i-vozobnovleniya.md)

## Что сделать
1. Детектор прерывания на старте приложения (lifespan): если sim_state.running и last_tick_at старше 3 тиков — текущий запуск → interrupted, running=false, событие runs.interrupted; агентские треды со status=running → interrupted.
2. ResumeService: проверка, что запуск — последний и в статусе paused/interrupted (иначе 409); восстановление RNG из sim_state.rng_state; возобновление LangGraph-тредов по префиксу run_id из PostgresSaver (шаг с незавершённым LLM-вызовом → retry, запись в agent_steps), пересчёт followups и таймеров поведения относительно sim_time; resumed_count++; событие runs.resumed.
3. Идемпотентность побочных эффектов при повторе шага: уведомления и задачи с idempotency_key (correlation_id + kind), чтобы повтор не создал дубли.
4. Graceful shutdown: SIGTERM → пауза тиков, flush чекпоинтов, статус paused (чтобы docker compose stop не оставлял interrupted без надобности).

## Критерии приёмки
- [ ] Сценарий: старт запуска, `docker compose kill backend` на середине обработки сигнала, `docker compose up` → запуск interrupted; POST resume → sim_time тот же, агент дообрабатывает сигнал без дублей уведомлений, followup срабатывает, метрики продолжают расти в том же run_id.
- [ ] Resume для stopped/completed возвращает 409 с понятным detail.
- [ ] Graceful stop оставляет статус paused и возобновляется без потерь.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/integration/test_resume.py
bash scripts/dev/kill_and_resume.sh
```

## Отчёт субагента
Ветка codex/T-041-resume, локальный checkpoint без PR/merge. StateGraph/Transactional PostgresSaver и0012 вschema langgraph; generatedrun_idFK и ARstatus. Строгийresume currentpaused/interrupted, sameRNG/time, recoverysameAR иretry, gracefulpause/drain.6PGactualrecoverypassed, послеnamespacedFK/lifecycle16PGpassed86.31s; Alembiccheck безdrift, licenses548green. Последниеизменениятребуютполногоregression/killupproof/coverage/contract+moneyreview; done не заявлен. Подробный review/rollback/compatibility: docs/reviews/T-041-durable-recovery.md.

Process checkpoint: настоящий SIGKILL собственного mock ASGI процесса и два restart (interrupted→resume, gracefulpaused→resume)1passed10.69s. SameAR/refund1/normalization1/sim_timepersisted/resumed_count+1; fullunit877/18skip и19startup/coreunitgreen. Dockerproductionнеостанавливался, liveLLMневызывался. Полныйcomposed/coverage/reviewвсёещёнужны.

### Составной кандидат recovery + maintenance + API1.5.17

Normal merge T0415758 + T0402a88, backend7b8b6b0:1261passed24skip в4изолированных
checkout/DB; точный aggregate exit0. Финальный UI-only097c5d8 имеет идентичный
backend tree, frontend167passed, real-image75Playwrightpassed (Graph/Trace
interrupted ru/en light/dark, static node, Resume, без browser mutations).
Scope/current/fresh/legacy/HITL timer tests сохранены и уточнены согласно
строгому stopped409 контракту; настоящие legacy AR без checkpoint не
возобновляются молча. API list/detail/nested/Trace показывают status и
interrupted_at до/после того же AR Resume; refund1/normalization1/token assertions
сохранены. Path-filter trace138passed, changed844/968=87.19%.

[Review, ограничения и screenshots](../reviews/T-041-maintenance-compose.md),
[машинные результаты](../reviews/T-041-maintenance-compose-proof.json).
Optional API1.5.17 и деньги/HITL атомарность требуют human review поAGENTS§5;
последующая SDK/P1 интеграция не включена в эти цифры. Общий DoD не закрыт.

### Stale control fence

Найдена и исправлена перезапись новых часов/RNG устаревшимконтроллером того же
currentrun: typed409 до effects, freshreload сохраняетT5. Native3RED→4GREEN26.00с,
allpublic table hashes unchanged после отказа, межпроверочнаягонка проверена.
[Review/границы](../reviews/T-041-stale-control.md). Broader checks/CI впереди,
общий DoD/карточка целиком не закрыты.

Peer review добавил status-only resurrection и shutdown bypass: оба actualRED,
плюс скрытый flush error. Followup7GREEN36.48с; typedValueError-compatible stale
skip/rollback/close, неожиданная storagefailure явно пробрасывается.
Прежний c92 broader56PG321.86с source-qualified; новый broader/CI ещё обязателен.
