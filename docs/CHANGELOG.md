# Журнал изменений пакета документации и контрактов

## v1.7.0 — 22.10.2026 — B08/B14 карта, зоны, KPI-дашборд и экономика dCLTV (cross-layer)
- `app/economics/dcltv.py`: формула ТЗ 14.4 (пострадавшие × доля детракторов × доля невозврата × (ставка + премиальная надбавка)), выбор ставки продукт → система → канал → fallback, класс исхода по статусу/SLA/подарку/регрессии/уходу, upsert `incident_economics` с `formula_ru`, ленивый пересчёт для открытых инцидентов, `calibration_mode = simulated` подставляет фактические коэффициенты удержания из `v_retention_by_outcome` (выборка ≥ 10).
- API: `/api/map/heat` (слои signals/critical/incidents/churn, окно, запуск), `/api/map/regions/{code}/cities`, `/api/map/zones` (индекс концентрации негатива + copilot, пороги `map_zone_thresholds` c `critical_red`), `/api/metrics/dashboard` (ТЗ 14.1), `/api/metrics/economics[/live|/fact|/fact/export|/calibrate]`, `/api/notifications`, `/api/incidents/{id}/economics`; в карточке инцидента `economics` заполнено.
- Frontend: вкладки «Карта» (TopoJSON 83 субъектов, `src/shared/geo/`, маркеры для субъектов без полигона, режимы Тепло/Зоны, drill-down до городов), «Дашборд» (12 KPI, экономика с группировкой, факт по симуляции, калибровка, CSV), «Уведомления» (центр исходящих); верхняя полоса KPI переведена на один запрос `/api/metrics/dashboard`.
- Тесты: `tests/unit/test_economics.py` (пример ТЗ 631,52 ₽), `tests/integration/test_map_metrics.py`.

## v1.6.0 — 22.10.2026 — B06/B16 Mock-АБС и публичная лента (cross-layer)
- Backend `app/abs/`: счёт на клиента, проводки двойной записи (`ledger_entries`: debit/credit/fee/refund), идемпотентный возврат по `correlation_id`, инвариант `balance = Σ проводок`, догоняющие проводки для операций сида/сценариев (`backfill_ledger` при старте, `post_operation` в генераторе). Политика автономии (ТЗ 9.3) теперь читает факты из АБС: «уже был возврат по операции», «возвратов за 30 дней».
- Агент: узел `act` возвращает комиссию инструментом `refund_fee` (автономно в лимите или после решения человека), закрывает инцидент как `resolved`, сканирует затронутых (`find_affected_clients`) и при массовом ударе ставит задачу `mass_refund` (HITL); текст клиенту — факт «возвращено», не обещание.
- `app/feed/`: посты эмулятора площадки (`external_posts`/`external_replies`), ответ под постом без ПДн и обещаний (`sanitize_public_text`), статусы `replied|escalated_to_dm`, статистика `v_feed_latency`. Посты создаются для всех публичных сигналов: симулятор, сценарии, жюри, `POST /api/public/reviews` (сопоставление автора по `card_last4`).
- API: `/api/abs/accounts/{client_id}`, `/api/abs/ledger`, `POST /api/abs/refunds` (HITL/массовый), `/api/public/feed[/{id}]`, `POST /api/public/reviews`, `POST /api/feed/{id}/reply`, `/api/feed/stats`, `/api/rules` (GET/PUT с версионированием, `POST evaluate`, `GET evaluations`).
- Frontend `/feed`: лента с фильтром по площадке, форма публикации отзыва, ветка ответов с латентностью, виджет «АБС (эмуляция)» с подсветкой возврата; WS-топики `feed`, `abs`.
- Сценарий 8 проверяет `refund`, `public_reply`, `abs_widget` (ранее NOT_YET). Тесты: `tests/integration/test_abs_feed.py`, `tests/unit/test_feed_sanitize.py`.

## v1.5.1 — 22.10.2026 — логирование и отчёт о качестве (T-222)
- JSONL-журнал structlog `backend/var/log/app.jsonl`, HTTP-метрики процесса, отчёт «что сломалось / работает не так / доработать» с рекомендациями и индексом здоровья: `GET /api/reports/quality|http|log`, `make report` → `data/reports/`, вкладка «Качество» на `/engine`. Контракт: `QualityReport`, `HttpStats`. Руководство — `docs/REPORTS.md`.

## v1.5.0 — 22.10.2026 — B07 комплаенс-контроль по транскриптам (cross-layer, contract-change)
- Backend `app/compliance/`: TXT/JSON-парсер транскриптов, таксономия и rule-детектор (8 паттернов, нечёткие фразы, факт-чек по `products.tariffs`, скрипт обслуживания с отрицаниями), LLM-детектор (`misselling_detect`, `transcript_report`; mock = правила; откат на правила при сбое), сессии/триггеры/счётчик/алерты/инциденты, отчёт (json|md) и отправка руководителю. API `/api/ingest/transcripts*`, `/api/compliance/*` реализованы (501 только для mic/file — B10).
- Сценарии 9 и 10 работают по файлам корпуса; корпус `data/import/transcripts` (20) проверяется тестом `tests/compliance/test_corpus.py` против `data/bench/transcripts_v1`.
- Frontend: `/compliance` (транскрипты, отчёт, реплики, статистика) и `/manager` (алерты с решением в один клик).
- Контракт: enum кодов паттернов в OpenAPI расширен до 8 (`MissellingPattern.code`, `ComplianceTrigger.pattern_code`); `.env.example` — `COMPLIANCE_ALERT_THRESHOLD`.

## v1.4.3 — 22.10.2026 — рабочий цикл одной командой
- `scripts/cx.py`: `doctor / next / start / check / pr / fix / status / done / clean / open` — worktree `../wt/<id>`, ветки `feat/T-NNN` и `pkg/Bxx`, окружение, промпт из `scripts/prompts/task.md`, запуск `codex exec` без участия человека (или Cursor/manual), проверки, PR через `gh` с отчётом агента и автоматическими метками `contract-change`/`cross-layer`, уборка после слияния. Состояние — `.cx/state.json`.
- `docs/WORKFLOW.md` (что такое worktree, пять команд, день целиком, что делать при сбоях); TEAM-SPLIT §4 и PLAN-14D §3 переведены на `cx`; AGENTS.md §3–4, §5.1.
- `.gitignore` в пакете (`.env`, `.cx/`, окружения, большая модель Vosk) — T-001 дополняет, не создаёт с нуля.

## v1.4.2 — 21.10.2026 — репозиторий GitHub, CI и проверка DDL на реальной базе
- Рабочий репозиторий — `github.com/florren/vibebashers`, зеркало в GitVerse (`mirror.yml`, уже в репозитории, проверено). `docs/REPO-BOOTSTRAP.md`: порядок заливки пакета при защищённой `main`, ruleset, тестовый PR.
- `.github/workflows/ci.yml`: job'ы `contracts`, `db` (PostgreSQL 16 service: `schema.sql`, идемпотентные 0002/0003 дважды, инварианты), `owners` (границы слоя в PR), `tests` (uv, ruff, mypy, pytest, npm — включаются по мере появления кода). Имена job'ов зафиксированы для ruleset.
- DDL проверен на реальном PostgreSQL (18): чистая v1.4, идемпотентность миграций, пути v1.2 → 0002 → 0003 и v1.3 → 0003, откат 0003 и повторный накат — 74 таблицы. Исправлено: `v_tickets` ссылалось на `clients.segment` вместо `clients.segment_code` (schema.sql и 0003).
- `Makefile`: алиас `check-contracts`; стек: `uv` как менеджер Python-окружения; AGENTS.md §2–3, §5.1; T-001 (CI усиливается без переименования job'ов, uv); TEAM-SPLIT §3/§6; PLAN-14D; ТЗ 16.3; CODEOWNERS (логины GitHub).

## v1.4.1 — 21.10.2026 — слои, владение и режим без ревьюера
- `docs/PLAN-14D.md`: спринт 22.10–4.11 — вертикальный демо-срез, 26 пакетов карточек по трём рабочим местам (Codex / Cursor / Perplexity Computer) и интегратору, список урезаний, контрольные точки с правилом отсечения, рычаги ускорения.
- `docs/TEAM-SPLIT.md`: пять слоёв L1–L5 с каталогами и субагентами, раскладка на 1–3 участников, режим слияния без ревьюера, распорядок для участника без опыта разработки, оценка сроков с учётом лимитов инструментов.
- `CODEOWNERS`, `scripts/check_owners.py` (`make check-owners`), `.github/pull_request_template.md`.
- Карточки: поля «Слой» и «В демо-минимуме»; индекс `docs/tasks/README.md` — колонки «Слой» и «Демо-мин.», раздел «По слоям» со сводкой объёмов.
- `AGENTS.md` §5.1, структура, §9; `CLAUDE.md`, `.cursor/rules`.

## v1.4 — 21.10.2026 — слияние с дополнительным ТЗ (FR-1 … FR-5)

Вход: `docs/TZ-additional.md` (приём транскриптов и сообщений, NLP-модуль, агент-маршрутизатор на tool calling, анализ транскрипта сотрудника, карта с зонами). Матрица покрытия — ТЗ 0.6, 15 конфликтов и решения — ТЗ 20.6 и `docs/BRD-merge-analysis.md` (раздел «Дополнительное ТЗ»).

### Документы
- `docs/TZ.md` → v1.4: 0.6 (матрица FR → ТЗ), 1.2 п. 19–22, 1.4 (принцип «имена наружу — из ТЗ заказчика»), 3.6–3.7 (приёмный слой, транскрипты, адаптеры), 7 (`sentiment`, `hidden_negativity`, `problem_summary`), 9.2 (роутер-инструменты), 9.3 (политика эскалации и уточнения), 9.7 (тикетница, эскалации, цепочка решений), 12.2 (зоны карты, тикер, поля ленты, вкладка «Транскрипты»), 12.5, 13, 14.1, 14.3 (наборы `sentiment_v1`, `hidden_negativity_v1`, `summary_v1`, `red_phrases_v1`, `transcripts_v1`), 16.4, 17 (E18), 18 (сценарии 10–11, блок D), 19 п. 26–33, 20.3 п. 7–10, 20.6, 22.8–22.9, 23.
- `AGENTS.md`: §1, стек, структура (`app/ingest`, `app/tickets`, данные ДТЗ), команды, железные правила 17–18, 6.2/6.8 дополнения, новая 6.10, §9 (E18, 150 карточек, критический путь v1.4), §10–11.
- `docs/tasks/`: 15 новых карточек T-207…T-221 (эпик E18), волны 2–4, демо-минимум v1.4.

### Контракты
- `contracts/db/schema.sql` v1.4 (74 таблицы, 9 представлений): `ingest_sources`, `ingest_messages`, `transcripts`, `escalations`, `service_scripts`; `signals.geo/sentiment/transcript_id`, `incidents.routing_status/problem_summary`, `misselling_patterns.family/alert_policy/immediate_threshold/recommendation_ru/training_module`, `compliance_triggers.recommendation_ru/fact_check`, `compliance_alerts.kind/recommendation_ru/transcript_id`, `audio_sessions.pacing/transcript_id/report`, `economics_settings.map_zone_thresholds`; CHECK `signals.origin += transcript, polling`, `compliance_alerts.decision += acknowledged`; представления `v_tickets`, `v_map_zones`; каналы NOTIFY `ingest`, `escalations`, `tickets`, `zones`.
- `contracts/db/migrations/0003_additional_tz.sql` + `alembic/versions/0003_additional_tz.py` (идемпотентно; downgrade возвращает v1.3).
- `contracts/api/openapi.yaml` 1.4.0: 131 путей (+21), 111 схем; теги `ingest`, `tickets`, `escalations`; `/api/ingest/messages`, `/api/ingest/transcripts*`, `/api/ingest/sources*`, `/api/public/mock-social-feed`, `/api/tickets*`, `/api/escalations*`, `/api/agent/runs/{id}/decision-chain`, `/api/compliance/transcripts/{id}/report|send`, `/api/compliance/scripts`, `/api/map/zones`, `/api/metrics/economics/live`, `/api/bench/sentiment`; поля `sentiment`, `geo`, `problem_summary`, `routing_status`, `channel` в `Signal`/`IncidentBrief`.
- `contracts/events/` (36 схем): новые `ingest/unified_message`, `ingest/transcript`, `ingest/ingest_event`, `agent/router_tools`, `agent/decision_chain`, `sim/escalation`, `sim/zone`, `compliance/transcript_report`; расширены `common` (+14 перечислений, флаги `passive_aggression`, `repeat_contact_7d`), `agent/normalization` (`sentiment`, `hidden_negativity`), `agent/classification` (`sentiment`, `problem_summary`), `agent/decision` (`router_action`, `escalation`, `clarification_question_ru`), `agent/tool_call` (+4 инструмента, `wraps`), `compliance/misselling_verdict` и `session_event` (семейство, рекомендация, `pacing`, `compliance.report_ready`), `envelope` (семейства `ingest|escalation|zone`), `ws/message` (топики `ingest`, `escalations`, `tickets`, `zones`, `metrics`).
- `Makefile`: `import-transcripts`, генерация схем `ingest` в `sync-contracts`.

Проверка: `python scripts/contracts_check.py` → 36 схем, 131 путей; `python scripts/gen_tasks.py` → 150 карточек.

## v1.3 — 21.10.2026 — слияние с бизнес-требованиями демо-стенда (BRD)

Вход: `docs/BRD.md` (сценарий 1 — внешние площадки и автономный возврат; сценарий 2 — аудиомониторинг и мисселлинг; NFR Log/Debug и отказоустойчивость демо). Обоснование решений и 17 конфликтов — `docs/BRD-merge-analysis.md`, журнал решений — ТЗ 20.5.

### Документы
- `docs/TZ.md` → v1.3: разделы 0.5 (матрица BRD → ТЗ), 1.2 п. 14–18, 1.3–1.4, 3.4 (stateful Mock-АБС), 3.6 (каналы `review_portal`, `voice_input`, `branch_audio`), 4.7 (живые контуры), 5.3 (`STTProvider`), 5.4 (подстраховка), 6 шаг 7a (быстрый путь), 8.1 (`instant`, `fee_refund`, `misselling`), 9.6 (Rules Engine), 11 и 12.2 экран 7 («Надиктовать»), 12.2 экраны 8–10, 12.6 (панель Log), 12.7 (меню демонстратора), 13 (17 таблиц), 14.3 (наборы `reviews_v1`, `misselling_v1`, `stt_v1`), 16.4 (бюджеты задержек), 17 (E15–E17), 18 (сценарии 8–9, демо-скрипт), 19 п. 18–25, 20.3, 20.5, 21–22 (новые разделы), 23 (источники).
- `AGENTS.md`: §1–4 (контуры, STT в стеке, структура, команды, HTTPS), железные правила 14–16, подсистемы 6.7–6.9, дополнения 6.2–6.6, §7 (идемпотентные миграции), §9 (E15–E17, сквозные), §10–11.
- `docs/tasks/`: 36 новых карточек T-171…T-206 (135 всего), волны и демо-минимум v1.3, критические пути контуров.

### Контракты
- `contracts/db/schema.sql` v1.3: 17 новых таблиц, колонки `clients.social_handles/refunds_30d`, `client_products.card_last4`, `operations.method/merchant/fee_amount`, `signals.voice_meta/external_post_id`, `economics_settings.misselling_case_cost_rub`, `incident_economics.refund_amount_rub`; CHECK-перечисления `sim_runs.kind += live`, `incidents.incident_type += fee_refund, misselling`, `incidents.complexity += instant`, `incidents.created_by += compliance`, `signals.origin += review_portal, voice_input, api`, `agent_runs.kind += compliance_detector, speaker_attribution`; представления `v_feed_latency`, `v_compliance_by_employee`; каналы NOTIFY `feed`, `abs`, `compliance`, `stt`, `demo`.
- `contracts/db/migrations/0002_brd_contours.sql` + `alembic/versions/0002_brd_contours.py` (идемпотентно; downgrade возвращает v1.2).
- `contracts/api/openapi.yaml` 1.3.0: +31 путь (теги `feed`, `abs`, `rules`, `compliance`, `stt`, `demo`), `/ws/audio/{session_id}`, `voice_meta` в `POST /api/signals` и `POST /api/public/claim`, +28 схем.
- `contracts/events/`: `common` (+17 перечислений, расширены `team`, `channel`, `flag`, `complexity`), `envelope` (семейства `review|abs|compliance|demo`), `ws/message` (топики `feed`, `abs`, `compliance`, `stt`, `demo`), `agent/tool_call` (+6 инструментов, `source`), `agent/decision` (`fast_path`, `rule_codes`), `agent/classification` (`negativity`, `intents`); новые `agent/normalization`, `agent/client_match`, `agent/rule_violation`, `agent/instant_decision`, `rules/rule_condition`, `sim/review`, `sim/abs`, `compliance/session_event`, `compliance/misselling_verdict`, `compliance/speaker_attribution`, `compliance/stt_result`, `demo/failover`.
- `Makefile`: цели `tasks`, `cassettes-record`, `stt-bench`, `demo-offline`; `sync-contracts` копирует `migrations/` и генерирует схемы `compliance`/`rules`.

Проверка: `python scripts/contracts_check.py` → 28 схем, 110 путей; `python scripts/gen_tasks.py` → 135 карточек.

## v1.2 — 21.10.2026
Запуски эмуляции (`sim_runs`, `run_id`), прерывание/возобновление, baseline-снимки (ТЗ 4.6).

## v1.1 — 20.10.2026
Модель поведения клиентов, калькулятор «Факт», ADR, карточки задач.
