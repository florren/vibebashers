# AGENTS.md — инструкции для кодирующих ИИ-агентов проекта CX Pulse Control

Этот файл читают все агенты и субагенты, работающие в репозитории `github.com/florren/vibebashers` (рабочий репозиторий: ветки, PR, CI) с автоматическим зеркалом в `gitverse.ru/florren/vibebashers` (репозиторий защиты, только приём; workflow `mirror.yml`). Он важнее любых предположений: если задача противоречит этому файлу или ТЗ — остановись и задай вопрос техлиду (Денис).

## 1. Что мы строим

CX Pulse Control — демонстрационный MVP ИИ-агента крупного банка, который собирает сигналы клиентов (соцсети, транскрипты звонков, чаты, письма, лендинг, Telegram-бот), классифицирует их, создаёт инциденты для продуктовых команд, проактивно уведомляет клиентов, отслеживает SLA, замыкает петлю подарком и считает экономику потерь. Банк эмулируется: клиенты с психотипами, подсистемы со сбоями, команды, 14 дней симулированной истории. С v1.3 добавлены два живых демонстрационных контура по бизнес-требованиям демо-стенда (`docs/BRD.md`): «внешняя площадка → автономный возврат комиссии → публичный ответ» (экран `/feed`, Mock-АБС, бизнес-правила) и «аудиомониторинг отделения → детектор мисселлинга → алерт руководителю» (экраны `/compliance`, `/manager`, офлайн STT), плюс режим подстраховки (кассеты `replay`, предзаписанные входы, меню демонстратора) и голосовой ввод жалобы «Надиктовать». Цель — демо 7–8 минут (короткая версия 3–5) на хакатоне с вводом от жюри.

Источник истины по требованиям — `docs/TZ.md` (ТЗ v1.4; обоснование слияния с BRD — `docs/BRD-merge-analysis.md`, с дополнительным ТЗ — ТЗ 0.6 и 20.6). v1.4 добавляет приёмный слой `ingest` (единая схема сообщения, транскрипты JSON/TXT, адаптеры REST/polling), трёхклассную тональность и скрытый негатив, роутер-инструменты агента с именами из ТЗ заказчика, тикетницу и эскалации, «красные фразы» сотрудника по готовому транскрипту и трёхцветные зоны карты. Имена наружу — из ТЗ заказчика, механика — внутренняя (ТЗ 1.4). Нумерация разделов в комментариях кода и задачах («ТЗ 8.2») ссылается на него. Контракты в `contracts/` обязательны к исполнению; меняются только через раздел 7 этого файла.

## 2. Стек (зафиксирован, не менять без ADR)

| Слой | Технология | Примечание |
|---|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2 (async, psycopg 3), Alembic, Pydantic v2 | один процесс `uvicorn`, фоновые задачи через `asyncio` + PostgreSQL LISTEN/NOTIFY; без Redis/Celery |
| Агент | LangGraph (StateGraph, checkpointer в PostgreSQL), langchain-gigachat, openai SDK для OpenAI-совместимых API | провайдеры за единым интерфейсом `app/llm/provider.py` |
| БД | PostgreSQL 16 | схема — `contracts/db/schema.sql` (v1.4), применяется миграцией `0001`; идемпотентные `0002` (v1.3) и `0003` (v1.4) доводят старые базы |
| STT | Vosk (vosk-api, Apache-2.0) внутри backend-воркера; модель `vosk-model-small-ru-0.22` в репозитории, `vosk-model-ru-0.42` — опциональная загрузка `install.sh --stt-model large` | единственный голосовой вход; провайдеры за интерфейсом `app/stt/base.py`; облачные (`browser`, `salutespeech`, `openai_compatible_audio`) выключены по умолчанию. TTS нет |
| Frontend | React 18, Vite, TypeScript strict, Tailwind, ECharts, React Flow, d3-geo, react-i18next, TanStack Query | без внешних CDN, шрифты Inter и JetBrains Mono локально |
| Бот | aiogram 3, long polling | отдельный сервис `tgbot/`, общается с backend по `/api/internal/tgbot/inbound` |
| Python-окружение | `uv` (`uv sync --frozen`, `uv run …`), `pyproject.toml` + `uv.lock` в `backend/` | pip/poetry не использовать; CI ставит uv через `astral-sh/setup-uv` |
| CI | GitHub Actions `.github/workflows/ci.yml`: job'ы `contracts`, `db` (PostgreSQL 16 service, schema.sql + идемпотентные миграции), `owners` (границы слоя в PR), `tests` | имена job'ов `contracts`/`db`/`tests` зафиксированы в ruleset ветки `main` — не переименовывать; `mirror.yml` зеркалит в GitVerse |
| Инфра | Docker Compose, `install.sh`, Caddy (опционально), Mailpit (опционально) | всё поднимается одной командой на Linux без внешних зависимостей, кроме API LLM и Telegram |

Все зависимости — открытые лицензии, разрешающие коммерческое использование (MIT, BSD, Apache-2.0, PostgreSQL, MPL-2.0). GPL/AGPL/SSPL и «source-available» — запрещены. Перед добавлением пакета проверь лицензию и запиши её в `docs/LICENSES.md`.

## 3. Структура репозитория

```
AGENTS.md                 этот файл
CLAUDE.md                 ссылка на AGENTS.md (для Claude Code)
.cursor/rules/            ссылка на AGENTS.md (для Cursor)
docs/TZ.md                техническое задание v1.4
docs/BRD.md               бизнес-требования демо-стенда (вход v1.3)
docs/TZ-additional.md     дополнительное ТЗ заказчика FR-1…FR-5 (вход v1.4)
docs/CHANGELOG.md         журнал изменений пакета
docs/TEAM-SPLIT.md        слои L1–L5, раскладка на 1–3 участников, режим без ревьюера, оценка сроков
docs/PLAN-14D.md          спринт до демо: пакеты карточек по дням и рабочим местам, урезания, контрольные точки (имеет приоритет над волнами на время спринта)
CODEOWNERS                владение каталогами по слоям (проверяется scripts/check_owners.py)
.github/pull_request_template.md  шаблон PR с чек-листом DoD
.github/workflows/ci.yml  CI (contracts / db / owners / tests); .github/workflows/mirror.yml — зеркало в GitVerse (уже в репозитории, не трогать)
docs/REPO-BOOTSTRAP.md    как залить пакет в репозиторий, настроить ruleset и проверить связку PR → CI → merge → зеркало
docs/WORKFLOW.md          рабочий цикл одной командой: scripts/cx.py (next/start/check/pr/done) — worktree, промпт, запуск агента, PR
scripts/cx.py, scripts/prompts/task.md  оркестратор рабочего цикла и шаблон промпта агенту; состояние в .cx/ (gitignore)
docs/BRD-merge-analysis.md анализ слияния BRD с ТЗ: конфликты и решения
docs/adr/                 архитектурные решения (ADR-NNNN-*.md)
docs/tasks/               карточки задач субагентам (T-NNN-*.md)
contracts/                контракты: db/, api/, events/  — источник истины
backend/                  FastAPI-приложение
  app/api/                роутеры по тегам OpenAPI (setup, settings, sim, signals, incidents, hitl, tasks, clients, map, metrics, engine, bench, public, feed, abs, rules, compliance, stt, demo)
  app/db/                 models.py (SQLAlchemy), session.py, repositories/
  app/observability/      JSONL-журнал structlog (var/log/app.jsonl), HTTP-метрики, отчёт о качестве (docs/REPORTS.md)
  app/sim/                симулятор: clock.py, generators/, behavior/ (психотипы, состояния, двойники), teams.py, sla.py, scenarios/
  app/agent/              graph.py, nodes/ (+ check_rules, act_instant), tools/ (+ router_tools.py — фасады ДТЗ), prompts/ (versioned, + hidden_negativity.md), policies.py (+ политика эскалации), schemas.py (Pydantic из contracts/events/agent)
  app/ingest/             v1.4: schemas.py (UnifiedMessage, Transcript), normalizer.py (все входы → единая схема → signals), transcripts.py (парсеры JSON/TXT, анализы), sources.py (адаптеры rest/polling/file), mock_feed.py
  app/tickets/            v1.4: v_tickets, эскалации (escalations), decision_chain.py (цепочка решений JSON/Markdown)
  app/abs/                Mock-АБС: счета, тарифы, проводки, идемпотентные возвраты (ТЗ 3.4)
  app/rules/              Rules Engine: интерпретатор условий business_rules, оценка перед решением агента (ТЗ 9.6)
  app/feed/               эмулятор внешней площадки: посты, публичные ответы, фоновая лента (ТЗ 21)
  app/stt/                base.py (STTProvider), vosk_provider.py, browser.py, salutespeech.py, audio_ws.py (/ws/audio)
  app/compliance/         sessions.py, speakers.py (stereo/manual/auto), rules_detector.py, llm_detector.py, counter.py, alerts.py (ТЗ 22); v1.4: batch.py (pacing=batch, transcript_report), fact_check.py, scripts.py (service_scripts), recommendations.py
  app/replay/             провайдер replay: кассеты записанных ответов моделей, запись LLM_RECORD (ТЗ 5.4)
  app/demo/               статус провайдеров, failover, запуск предзаписанных входов, активы (ТЗ 12.7)
  app/llm/                provider.py, gigachat.py, openai_compat.py, mock.py, failover.py (таймауты по контексту), ratelimit.py, keys.py
  app/economics/          dcltv.py, calibration.py
  app/realtime/           ws.py, notify.py (LISTEN/NOTIFY → WebSocket)
  app/bench/              runner.py, metrics.py
  app/i18n/               тексты уведомлений ru/en для шаблонов
  alembic/, schema.sql, migrations/  копия contracts/db (обновляется make sync-contracts)
  tests/                  pytest: unit/, integration/, scenarios/
frontend/                 Vite + React
  src/app/                роутинг, layout, темы
  src/features/           по экранам: setup, workspace, incidents, hitl, engine, bench, settings, landing, tracking, economics, feed, compliance (+ transcripts), manager, demo-menu, tickets (переключатель терминов, цепочка решений)
  src/shared/audio/       useMicrophone, AudioWorklet-процессор, клиент /ws/audio, компонент <VoiceInput>
  src/shared/components/LogPanel  панель «Log/Debug» для демо-экранов (ТЗ 12.6)
  src/shared/api/         клиент из OpenAPI (openapi-typescript), ws.ts
  src/shared/i18n/        ru.json, en.json
  public/map/russia.svg   контуры субъектов РФ (лицензия в data/README.md)
tgbot/                    aiogram-бот
data/                     справочники: regions.csv, cities.csv, segments.yaml, psychotypes.yaml, error_codes.yaml, dcltv_rates.csv, gifts.yaml, templates/, golden/
  rules.yaml, tariffs.yaml, misselling_patterns.yaml, branches.yaml   v1.3: правила, тарифы Mock-АБС, таксономия нарушений (v1.4: + семейство conduct), отделения
  service_scripts.yaml, ingest_sources.yaml   v1.4: эталонный скрипт обслуживания, адаптеры источников demo-профиля
  import/transcripts/, import/messages/       v1.4: транскрипты JSON/TXT и сообщения для импорта (transcripts_v1)
  bench/sentiment_v1.jsonl, hidden_negativity_v1.jsonl, summary_v1.jsonl, red_phrases_v1.jsonl   v1.4: наборы ДТЗ
  corpus/reviews/, corpus/dialogs/   корпуса отзывов и диалогов отделения
  models/stt/             vosk-model-small-ru-0.22 (в репозитории), large — в .gitignore
  audio/, cassettes/      предзаписанные WAV с эталонами (*.ref.json) и кассеты replay (*.jsonl)
  stt/vocab_ru.txt        словарь терминов для STT
scripts/                  install.sh, seed/*.py, bench.sh, dev.sh, stt_bench.py, gen_tasks.py, contracts_check.py
docker-compose.yml, .env.example, Makefile
```

Не создавай новых каталогов верхнего уровня без согласования.

## 4. Как запустить и проверить

```bash
cp .env.example .env            # заполни GIGACHAT_* / OPENROUTER_API_KEY / TELEGRAM_BOT_TOKEN
./install.sh --profile lite     # docker compose up, миграции, сид, health-check, адрес мастера
./install.sh --offline          # без сети: LLM replay → mock, STT vosk, бот выключен, предзаписанные входы
./install.sh --stt-model large  # скачать большую модель Vosk (точнее, ~6 ГБ ОЗУ); --no-stt — без STT-воркера
./install.sh --record-cassettes # LLM_RECORD=1: записывать ответы моделей в кассеты на репетиции
make dev                        # backend (uvicorn --reload) + frontend (vite) без docker, нужна локальная PostgreSQL
make test                       # pytest + vitest + проверки контрактов
make lint                       # ruff, mypy --strict (app/), eslint, tsc --noEmit
make sync-contracts             # копирует schema.sql и генерирует TS-типы/ Pydantic из contracts/
make scenario ID=deposit_promo_rate   # прогон демо-сценария с проверкой ожиданий
make scenario ID=qr_fee_public_review # сценарий 8 (BRD-1) на кассете
make scenario ID=branch_misselling    # сценарий 9 (BRD-2) из транскрипта/WAV
make cassettes-record SCENARIO=…      # записать кассеты replay
make stt-bench                        # WER и задержки STT на наборе stt_v1
make scenario ID=retail_transcript_red_phrases   # сценарий 10 (ДТЗ) — транскрипт с грубостью и неверной ставкой
make scenario ID=social_sarcasm_escalation       # сценарий 11 (ДТЗ) — сарказм → уточнение → эскалация
make bench SET=sentiment_v1           # accuracy трёхклассной тональности (порог 0,80)
make import-transcripts               # импорт data/import/transcripts/ (JSON/TXT)
make report                           # отчёт о качестве → data/reports/ (что сломалось / работает не так / доработать; docs/REPORTS.md)
python scripts/cx.py next|start|check|pr|fix|status|done   # рабочий цикл карточки/пакета в отдельном worktree (docs/WORKFLOW.md)
```

Микрофон в браузере работает только по HTTPS или на `localhost` — на демо открывай UI с ноутбука (localhost) или через Caddy с TLS; `install.sh` предупреждает, если `APP_PUBLIC_URL` небезопасен.

Любая задача считается выполненной только если `make lint && make test` проходят локально и в CI (`.gitverse/workflows` или GitHub Actions-совместимый YAML в `.github/workflows/ci.yml`).

## 5. Железные правила

1. **Контракты первичны.** Код подстраивается под `contracts/`, а не наоборот. Перечисления берутся из `contracts/events/common.schema.json` (генерация: `make sync-contracts` → `backend/app/contracts/enums.py`, `frontend/src/shared/contracts/enums.ts`). Дублировать списки сегментов/команд/статусов руками запрещено.
2. **Все записи в БД от имени агента идут через инструменты** (`app/agent/tools/*`, список — `contracts/events/agent/tool_call.schema.json`). Узлы графа не пишут в БД напрямую. Каждый вызов инструмента логируется в `agent_steps.tool_calls`.
3. **Структурированные выходы LLM валидируются** Pydantic-моделями, сгенерированными из `contracts/events/agent/*.schema.json`. При невалидном JSON — один retry с сообщением об ошибке валидации, затем fallback на mock-провайдер с пометкой `status = fallback`. Никогда не парсить ответ модели регулярками «на глаз».
4. **Нет реальных ПДн.** Имена — из синтетических списков, телефоны только в диапазоне `+7 900 000-00-00 … +7 900 009-99-99`, e-mail только `@example.ru`/`@example.com`, карты только `**** NNNN`. Тест `tests/unit/test_no_pii.py` проверяет сид и шаблоны.
5. **Секреты только в `.env`** и `llm_api_keys.encrypted_key`. Никаких ключей в коде, тестах, логах, фикстурах, скриншотах. Логи LLM-вызовов маскируют заголовки `Authorization`.
6. **Детерминизм симуляции.** Любая случайность — через `app/sim/rng.py` (seeded `numpy.random.Generator`), сид хранится в `sim_state.seed`, состояние генератора — в `sim_state.rng_state` (для возобновления). Два запуска с одним сидом от baseline и mock-LLM дают одинаковые `sim_events` и `summary`.
7. **Симуляционное время отдельно от реального.** Поля `*_sim` — из `SimClock`, поля `*_at` — `now()`. SLA, терпение клиентов, отчёты команд считаются в рабочих днях симулятора (пн–пт, 09:00–18:00 по `sim_state`).
8. **Без внешних сетевых вызовов**, кроме: API LLM-провайдеров, Telegram Bot API (если включён), OpenRouter `GET /api/v1/key` и `/api/v1/models`. Шрифты, карты, иконки — в репозитории. Тест `tests/integration/test_no_cdn.py` проверяет собранный фронтенд.
9. **Локализация.** Весь текст интерфейса — через `t('key')`, словари `ru.json`/`en.json` полные (проверка `make i18n-check`). Тексты клиенту генерируются на языке сигнала (по умолчанию ru). В коде/комментариях/коммитах — русский; идентификаторы — английский.
10. **Дизайн.** Токены из `frontend/src/app/theme/tokens.css` (ТЗ 12.1): основной `#21A038`, градиент `#21A038 → #0098F8`, акцент `#F1E813`. Никаких логотипов и названий реальных банков в UI, данных и тестах — везде «Банк».
11. **Производительность демо.** Профиль `demo` (5 000 клиентов, 14 дней) генерируется ≤ 90 с на 4 ядрах; p95 ответа API ≤ 300 мс при работающей симуляции; WebSocket-обновления ≤ 1 с. Тяжёлые агрегаты — через представления `v_*` и индексы из `schema.sql`, не через ORM-циклы.
12. **Одна задача — одна ветка — один PR.** Ветки `feat/T-012-slug`, `fix/…`, `chore/…`. Коммиты по Conventional Commits на русском после префикса: `feat(agent): узел classify со structured output`. PR содержит: ссылку на карточку задачи, что сделано, как проверить, скриншот/лог, список затронутых контрактов.

13. **Запуски эмуляции изолированы (ТЗ 4.6).** Любая строка, порождённая симулятором или агентом, несёт `run_id` текущего запуска (`sim_state.current_run_id`, contextvar в `app/sim/runs.py`); INSERT без `run_id` в таблицу с такой колонкой — ошибка. Метрики, дашборд и калькулятор по умолчанию считаются по текущему запуску (параметр `run_id=current|all|<id>`), ленты и карточки — baseline + текущий. Повторный запуск сценария = новый `sim_run` с режимом `counters` или `baseline` (восстановление из `data/baseline/<profile>.dump`); никакого ручного «подчищения» таблиц. Состояние, нужное для возобновления (RNG, чекпоинты LangGraph, followups), хранится в БД, а не в памяти процесса; побочные эффекты идемпотентны по `correlation_id`.

14. **Деньги — только по правилу (ТЗ 1.4, 9.6).** Любая проводка `ledger_entries.kind in ('refund','reversal')` от имени агента создаётся исключительно инструментом `refund_fee` и только при наличии `rule_evaluations.result = 'matched'` для той же операции, в пределах лимита автономии из `policies.py`, идемпотентно по `correlation_id`. LLM не может инициировать движение денег «по своему мнению»: нет правила — `request_human_decision`. Массовые возвраты (≥ `mass_refund_threshold`) — всегда через HITL и `POST /api/abs/refunds`. Публичный ответ под постом публикуется только инструментом `publish_public_reply` с проверкой на ПДн и запрещённые обещания.
15. **Живые контуры не зависят от сим-времени (ТЗ 4.7).** `/feed`, `/compliance`, «Надиктовать» работают при паузе симулятора и без запуска: сервис `ensure_live_run()` создаёт `sim_runs.kind = 'live'`. Задержки этих контуров измеряются реальным временем и обязаны укладываться в бюджеты ТЗ 16.4 (первое действие ≤ 2 с, цепочка p50 ≤ 10 с, STT partial ≤ 0,5 с, правило ≤ 0,3 с, детектор ≤ 2 с, счётчик ≤ 3 с, алерт ≤ 1 с); превышение логируется в трассировку, а LLM-шаг дольше таймаута переключается на `replay → mock` без разрыва цепочки.

16. **Честная подстраховка (ТЗ 5.4, 12.7).** Офлайн-ответы берутся из кассет реальных моделей (`replay`), а не придумываются; каждый шаг несёт источник `live | replay | mock`, в UI всегда виден тихий бейдж режима. Кассеты и предзаписанные аудио не содержат секретов и реальных ПДн, аудио живых сессий по умолчанию не сохраняется (`audio_sessions.store_audio = false`), сохраняется только текст реплик. Мисселлинг анализируется только по речи сотрудника; клиенту разъяснение уходит только после решения человека.

17. **Один вход — одна схема (ТЗ 3.7).** Любой сигнал создаётся только через `app/ingest/normalizer.py` из `UnifiedMessage` (канал, клиент, текст, timestamp, гео); прямые `INSERT` в `signals` мимо нормализатора запрещены, включая симулятор и тесты. Идемпотентность — по `(source_code, external_id)`.

18. **Имена наружу — из ТЗ заказчика (ТЗ 1.4, 9.2).** Роутер-инструменты `route_to_department`, `notify_customer`, `escalate_to_manager`, `request_clarification` — фасады с точными сигнатурами из `router_tools.schema.json`; они идут первыми в списке функций модели и логируются одним шагом с `wraps=[…]`. Поля `sentiment`, `problem_summary {problem, severity, suggested_team}`, `router_action` обязательны в выходах агента; `router_action` обязан совпадать с фактическими вызовами (`policy_checks`). Тикет = инцидент (`v_tickets`), второго хранилища нет.


### 5.1 Работа в слоях и режим без ревьюера (docs/TEAM-SPLIT.md)

- Каждая карточка/пакет выполняется в отдельном worktree `../wt/<id>` на ветке `feat/T-NNN` или `pkg/Bxx`; создаёт, запускает агента и открывает PR `scripts/cx.py` (`docs/WORKFLOW.md`). Если ты запущен через `cx`, не пушь и не открывай PR сам — это делает `cx pr`.
- Каждая карточка принадлежит слою `L1`–`L5` (поле «Слой» в карточке). Агент меняет файлы только внутри каталогов своего слоя по `CODEOWNERS`; общие каталоги тестов — только добавлять. Проверка: `python scripts/check_owners.py --base main` (слой берётся из имени ветки `feat/T-NNN-*`).
- Если для карточки нужно изменить `contracts/` или файл другого слоя — остановись, опиши требуемое изменение в блоке «Отчёт» карточки и в описании PR с меткой `contract-change` / `cross-layer`. Такие PR сливает владелец L1; остальные сливаются по зелёному CI без ревью человека.
- Ветка `main` защищена ruleset'ом: только через PR, обязательные проверки `contracts`, `db`, `tests`, ветка должна быть актуальна. Перед PR обязательны: `git rebase main`, `make lint`, `make test`, `python scripts/contracts_check.py`, `python scripts/check_owners.py`, заполненный блок «Отчёт» и шаблон `.github/pull_request_template.md` с отмеченным DoD. PR без отчёта и без вывода проверок считается незавершённым.
- Подтверждение человека нужно только в трёх случаях: изменение контрактов, всё, что касается денег и HITL (`refund_fee`, политики, лимиты), удаление или переименование файлов чужого слоя.
- Контракты меняются только вперёд (новые поля/пути — да, переименование/удаление — только через версию и миграцию, §7).

## 6. Правила по подсистемам

### 6.1 Симулятор (`app/sim`)
- Шина событий: `sim_events` + `pg_notify('sim_events', …)`. Формат — `contracts/events/envelope.schema.json`. Каждое событие валидируется перед записью (в dev/test — всегда, в prod — выборочно 10 %).
- Генераторы: операции (пуассоновские интенсивности по сегментам и часам), сбои (длительность, регион, доля затронутых), ошибки клиентов, команды (`speed_profile` из `teams`), SLA-тик каждые 15 сим-минут, модель поведения (ТЗ 4.5).
- Регрессии: при `team.release` с вероятностью `teams.speed_profile.p_regression` (по умолчанию 0,12) через 60–240 сим-минут создаётся `fault.regression` в смежной системе того же продукта с `faults.caused_by_incident_id`.
- Поведение клиентов: параметрическая модель для всех; LLM-двойники только для «подсвеченных» (сценарии, HITL, vip/ultra_vip, выборка ≤ `settings.twins.daily_limit`). Промпт двойника получает только то, что клиент реально видел (уведомления, ответы), а не внутренние поля инцидента.
- Уход клиента → `churn_events` + инцидент `account_closure` (team_cx) + `clients.is_active = false`; продукты закрываются; событие `client.account_closure`.

### 6.2 Агент (`app/agent`)
- Граф LangGraph: `ingest → normalize → identify_client → gather_context → check_rules → [fast_path → act_instant → verify → close → gift] | classify → decide → (wait_human) → act → followup_monitor → verify → close → gift`. Быстрый путь (ТЗ 21.4) разрешён только при `rule_violation.matched`, идентификации ≥ 0,8 и политиках `fast_path_allowed`; один вызов основной модели со схемой `instant_decision`. Узлы — чистые функции над `AgentState` (TypedDict), побочные эффекты — только в инструментах.
- Промпты версионируются в `app/agent/prompts/vN/*.md` c фронтматтером (`version`, `model_hints`, `output_schema`). Версия пишется в `agent_runs.prompt_version`. Менять промпт = новая версия + прогон `make bench DATASET=lite`.
- Политики HITL (ТЗ 9.3) — в `policies.py` как чистые функции `needs_human(classification, context) -> HumanReason | None`; покрыты unit-тестами на каждую ветку.
- Запрещённые формулировки клиенту (обещания сроков вне SLA, обвинения, упоминание внутренних систем) — проверка `promise_check` в `act`; при нарушении — перегенерация, затем шаблон.
- Трассировка: каждый узел пишет `agent_steps` (вход, выход, промпт, сырой ответ, reasoning, токены, латентность) и шлёт `agent/step_*` и `agent_tokens/delta` в WebSocket. Это основа экрана «Под капотом» — не экономь на деталях.
- Дедупликация: `find_related_incidents` по `error_code + system + окно 4 сим-часа + регион`; `mass_impact` увеличивается, сигнал линкуется, клиенту — ответ с ссылкой на уже идущую работу.
- v1.4: нормализация дополнительно даёт `sentiment` (три класса, сверка с порогами `negativity` ≤33/34–66/≥67) и `hidden_negativity` (few-shot промпт `hidden_negativity.md`, `evidence_ru` — подстрока текста); классификация — `problem_summary` (≤ 2 предложений, валидатор в коде, один ретрай); решение — `router_action`. Политика эскалации (`policies.py`): угроза ухода при `negativity ≥ 80`, повтор при `sentiment = negative`, `severity = critical`, ≥ 3 обращений за 7 дней → `escalate_to_manager` обязателен; уточнение — не более одного подряд.
- Нормализация (`normalization.schema.json`) всегда даёт `negativity` 0–100, `intents[]`, `entities`, `contacts_hint`; идентификация по косвенным данным — инструмент `match_client_by_hints` (`client_match.schema.json`), `ambiguous` никогда не ведёт к автономным деньгам.

### 6.3 LLM-провайдеры (`app/llm`)
- Единый интерфейс: `complete_structured(messages, schema, profile) -> (obj, usage, raw)`, `stream(...)`. Реализации: `gigachat.py` (langchain-gigachat, Authorization key → access token с автообновлением), `openai_compat.py` (openai SDK, `base_url` из профиля — OpenRouter, локальная модель), `mock.py` (правила + шаблоны, детерминирован).
- Пул ключей GigaChat: выбор ключа с наибольшим остатком `tokens_limit - tokens_used`; при 429/квоте — следующий ключ; учёт `usage` после каждого ответа.
- Rate limiter per profile (`rpm_limit`, `rpd_limit`) — token bucket в памяти + счётчик в `llm_api_keys.requests_today`. OpenRouter free по умолчанию: 18 RPM (запас к 20), 1 000/сутки.
- Модели по умолчанию в профилях OpenRouter: `nvidia/nemotron-3-ultra-550b-a55b:free`, `openrouter/owl-alpha`, `openai/gpt-oss-120b:free`. Мастер проверяет доступность через `GET /api/v1/models` и предлагает замену при отсутствии.
- Любая ошибка провайдера → `fallback_mock`, симуляция не останавливается. Ошибки видны в `agent_runs.error` и на экране бенчмарков.
- Провайдер `replay` (`app/replay`): ключ `sha256(provider, model, normalized_messages, schema)`, воспроизведение потока с исходными задержками, промах → следующий провайдер цепочки. Запись при `LLM_RECORD=1`. Таймауты по контексту — `app/llm/failover.py`: fast_path 8 с, detector 2 с, default 30 с.

### 6.4 Экономика (`app/economics`)
- Формула только одна, из ТЗ 14.4: `potential = affected × detractor_share × no_return_share × (rate + premium_addon)`. `rate` — по `dcltv_rates.maps_to` (продукт → система → канал); не найдено → `economics_settings.fallback_rate_code` (`bank_average`, 4 050 ₽).
- `prevented = potential × retention_factor[outcome_class]`; в режиме `simulated` коэффициент берётся из `v_retention_by_outcome` (при выборке < 10 — ручной с пометкой).
- Расчёт пересчитывается при каждой смене `incidents.status`/`outcome_class`, результат — в `incident_economics` с развёрнутым `breakdown` и `formula_ru`.
- v1.3: для `fee_refund` из `prevented` вычитается `refund_amount_rub`; для `misselling` `potential = economics_settings.misselling_case_cost_rub` (по умолчанию 4 050 ₽, помечено «требует согласования»), `prevented` — при решении руководителя `go` до закрытия сделки.

### 6.5 Frontend
- API-клиент и типы генерируются из `contracts/api/openapi.yaml` (`openapi-typescript` + лёгкий fetch-обёртка); ручные интерфейсы для ответов API запрещены.
- Состояние сервера — TanStack Query + инвалидация по WebSocket-сообщениям; локальное UI-состояние — Zustand.
- Каждый экран из ТЗ 12.2 — отдельная папка в `features/` с `index.tsx`, `api.ts`, `components/`, `__tests__/`. Сторибук не используем; визуальная проверка — Playwright-смоук со скриншотами в `frontend/e2e/`.
- Доступность: контраст ≥ 4.5:1 в обеих темах, фокус-стили, `aria-label` на иконках-кнопках, таблицы с заголовками.
- Исключение из «сайт не должен кричать» (ТЗ 12.1) — только экраны `/compliance` и `/manager`: красная заливка и звук при алерте. На рабочем месте CX тот же инцидент — обычная «тихая» карточка.
- Захват микрофона — только через `shared/audio/useMicrophone` и `<VoiceInput>`; без HTTPS/localhost кнопка скрыта с подсказкой, текстовый ввод остаётся.

### 6.6 Данные и сид (`scripts/seed`, `data/`)
- Сид идемпотентен (`ON CONFLICT DO NOTHING` / проверка `settings.seed_done`). Профили: `lite` 1 000 клиентов, `demo` 5 000, `stress` 20 000.
- Матрица покрытия (ТЗ 4.4) считается после сида и записывается в `settings.coverage`; тест `tests/integration/test_coverage.py` требует ≥ 1 сигнала на каждую комбинацию тип × продукт × канал и ≥ 3 инцидентов на каждую ячейку SLA.
- Тексты сигналов: шаблоны + вариативность по психотипу и тону; минимум 25 % сигналов с сарказмом/иронией/сленгом/опечатками, чтобы правила не справлялись, а LLM справлялась (нужно для панели «ИИ против правил»).
- Справочники регионов/городов — CSV с указанием источника и лицензии в `data/README.md`; все 89 субъектов, ≥ 300 городов.
- v1.3: у 60 % клиентов `social_handles` (синтетические ники), у карточных продуктов `card_last4` из невалидных по Луну номеров; 3–5 % QR-операций — с ошибочной комиссией `PROC-QR-FEE-CHARGED`; 10 отделений × 6 сотрудников с синтетическими ФИО; предзаписанные аудио — только голоса участников команды с согласия или синтез.

### 6.7 Mock-АБС и правила (`app/abs`, `app/rules`) [BRD]
- Баланс счёта всегда равен сумме проводок (инвариант проверяется тестом); комиссия — отдельная проводка `fee`, возврат — `refund` со ссылкой `refund_of_entry_id`; дублей по `correlation_id` нет.
- Правила — данные (`business_rules.condition` по `rules/rule_condition.schema.json`), не код; изменение правила увеличивает `version`, версия пишется в `rule_evaluations`. Интерпретатор детерминирован, ≤ 300 мс на окно 72 ч; результат — `rule_violation.schema.json` с `evidence`.
- Четыре правила v1: `RULE-QR-FEE-001` (возврат), `RULE-DOUBLE-DEBIT-001` (возврат), `RULE-PROMO-RATE-001` (HITL), `RULE-NOTIF-DUP-001` (подавление дублей). Новые правила — через `data/rules.yaml` и карточку с пометкой `rules-change`.

### 6.8 STT и комплаенс (`app/stt`, `app/compliance`) [BRD]
- `STTProvider`: `start_stream / feed / partial / final / health`; Vosk по умолчанию, модель грузится один раз при старте, пул процессов, пользовательский словарь `data/stt/vocab_ru.txt`. `/ws/audio/{session_id}`: PCM16 LE 16 кГц, кадры 100 мс, 1–2 канала; сообщения по `compliance/stt_result.schema.json`.
- Роли спикеров: `stereo` (канал), `manual` (пробел на экране), `auto` (Lightning по `speaker_attribution.schema.json`, < 0,7 → `unknown`, не анализируется). Анализируются только реплики `employee`.
- Детектор — гибрид: `rules_detector` (предварительная отметка ≤ 300 мс) → `llm_detector` (подтверждение ≤ 2 с, `misselling_verdict.schema.json`, цитата обязана быть подстрокой реплики). Не более одного триггера на реплику; счётчик по `confirmed`; `dismissed` уменьшает счётчик; алерт однократный за сессию, ≤ 1 с после порога, затем инцидент `misselling` в `team_compliance` с HITL руководителя.
- Все вызовы LLM детектора трассируются в `agent_runs(kind='compliance_detector')` — это тоже «Под капотом».
- v1.4: таксономия `misselling_patterns` имеет семейства `misselling` и `conduct` (`rudeness`, `script_violation`, `misinformation`) и политики алерта `counter` / `immediate` / `report`; `misinformation` всегда с `fact_check` из БД (`products`, `tariffs`), без подтверждённого факта — только «требует проверки». Пакетный режим `pacing = batch` (готовый транскрипт): один проход правил + один вызов LLM на транскрипт → `transcript_report` (≤ 10 с на 60 реплик), затем алерты по политикам и `recommendation_ru` в каждой находке. Batch — обязательная страховка живого режима.

### 6.9 Подстраховка и меню демонстратора (`app/replay`, `app/demo`, `features/demo-menu`) [BRD]
- Меню открывается только `Ctrl+Shift+R` или долгим нажатием на логотип; не рендерится в обычном режиме и не попадает в скриншоты README. Любое переключение → событие `demo.failover` (`demo/failover.schema.json`) и бейдж в футере.
- Предзаписанные входы (`demo_assets`): пост сценария 8, WAV/транскрипт сценария 9 — проигрываются через те же конвейеры (аудио — через тот же Vosk), а не «подставляются» в результат.
- Кассеты сценариев 8–9 перезаписываются при смене `prompt_version` (`stale` в `GET /api/cassettes`); автотесты сценариев всегда идут на кассетах.

### 6.10 Приёмный слой, тикетница и зоны карты (`app/ingest`, `app/tickets`, карта) [ДТЗ]
- `normalizer.py` — единственная точка создания сигналов; функции `from_*` для каждого входа, каскад гео `client_profile → contact → message → ip_mock (demo) → none`. Журнал `ingest_messages` фиксирует accepted/duplicate/rejected.
- Транскрипты: TXT-парсер терпим к форматам (таймкод опционален, синонимы ролей), но роль каждой реплики обязана быть определена — иначе 422 с указанием строки. Анализы `client_signal` и `employee_quality` независимы и идемпотентны (повторный `analyze` не плодит сигналы).
- Адаптеры `ingest_sources`: polling только через фоновый воркер с `interval_s ≥ 5`, курсор и статистика в БД; внешние URL помечаются `is_external`. В demo-профиле — только встроенная mock-лента.
- Тикетница: никаких таблиц `tickets`; `v_tickets` и `routing_status` на инциденте. Цепочка решений строится из `agent_steps` + `tool_calls` (`decision_chain.schema.json`), `why_ru` — из `rationale_ru`, ПДн маскируются.
- Зоны карты: только `v_map_zones` и пороги из `economics_settings.map_zone_thresholds`; пересчёт по событиям с дебаунсом, событие `zone.changed`; легенда с подписями (не только цвет).

## 7. Как менять контракты

1. Открой issue/карточку с пометкой `contract-change`, опиши причину и затронутых потребителей.
2. Внеси правку в `contracts/` (schema.sql → новая миграция Alembic `NNNN_*.py` (идемпотентный SQL в `contracts/db/migrations/`, как `0002_brd_contours.sql`), никогда не правь `0001`; openapi.yaml → обнови версию `info.version`; JSON-схема → обнови `title`/описание, при несовместимости — новое имя файла с суффиксом `_v2`).
3. Запусти `make sync-contracts && make test`. Обнови `docs/TZ.md`, если изменилось поведение.
4. В PR пометь `contract-change`; ревью техлида обязательно.

## 8. Определение готовности (Definition of Done)

- Код соответствует контрактам; `make lint && make test` зелёные; покрытие нового кода ≥ 80 % (backend), критичные компоненты фронта покрыты vitest.
- Нет TODO без ссылки на карточку задачи; нет закомментированного кода; нет `print` (только `structlog`).
- Для UI — скриншот обеих тем и обоих языков в PR; для агента — пример `agent_runs` с шагами в описании PR; для симулятора — выдержка `sim_events`.
- Обновлены `docs/TZ.md` (если менялось поведение), `docs/LICENSES.md` (если добавлены зависимости), `.env.example` (если добавлены переменные), `README.md` (если менялся запуск).
- Проверено на профиле `lite` в офлайн-режиме (`--offline`, mock LLM) и с реальным GigaChat хотя бы на одном сценарии.

## 9. Карта эпиков и субагентов

| Эпик | Субагент(ы) | Карточки | Ключевые файлы |
|---|---|---|---|
| E1 Каркас, БД, установка | `SA-DB`, `SA-Infra`, `SA-UI-Workspace` | 10 шт.: T-001…T-010 | docker-compose.yml, install.sh, backend/app/db, alembic |
| E2 Справочники и генераторы данных | `SA-Clients`, `SA-DB`, `SA-Logs`, `SA-Refs`, `SA-Signals` | 12 шт.: T-011…T-022 | data/, scripts/seed, app/sim/generators |
| E3 Симулятор банка, команды, SLA | `SA-Agent`, `SA-Economics`, `SA-Logs`, `SA-Scenarios`, `SA-Teams` | 12 шт.: T-031…T-042 | app/sim/clock.py, runs.py, baseline.py, teams.py, sla.py |
| E4 LLM-слой | `SA-LLM` | 6 шт.: T-046…T-051 | app/llm |
| E5 Агент LangGraph | `SA-Agent`, `SA-Prompts` | 12 шт.: T-056…T-067 | app/agent |
| E6 HITL и подарки | `SA-Agent`, `SA-UI-Workspace` | 5 шт.: T-076…T-080 | app/api/hitl.py, tasks.py |
| E7 Рабочее место CX | `SA-Map`, `SA-UI-Workspace` | 9 шт.: T-086…T-094 | frontend/src/features/workspace, incidents, hitl |
| E8 «Под капотом» | `SA-UI-Engine` | 5 шт.: T-106…T-110 | frontend/src/features/engine, app/realtime |
| E9 Лендинг, трекинг, Telegram-бот | `SA-Landing`, `SA-TgBot` | 4 шт.: T-119…T-122 | frontend/src/features/landing, tracking; tgbot/ |
| E10 Бенчмарки и экономика | `SA-Bench`, `SA-Economics` | 5 шт.: T-129…T-133 | app/bench, app/economics, features/bench, economics |
| E11 Сценарии и тесты | `SA-QA` | 6 шт.: T-141…T-146 | backend/tests/scenarios, frontend/e2e |
| E12 Документация и защита | `SA-Docs` | 4 шт.: T-151…T-154 | README.md, docs/ |
| E13 Локализация | `SA-i18n` | 2 шт.: T-156…T-157 | frontend/src/shared/i18n, app/i18n |
| E14 Поведение клиентов и калькулятор «Факт» | `SA-Behavior`, `SA-Economics`, `SA-QA` | 7 шт.: T-161…T-167 | app/sim/behavior, app/economics/calibration.py, features/economics |
| E15 Внешние площадки и автономный возврат [BRD] | `SA-ABS`, `SA-Agent`, `SA-UI-Feed`, `SA-Signals`, `SA-QA`, `SA-Teams` | 10 шт.: T-171…T-180 | app/abs, app/rules, app/feed, app/agent/nodes/{check_rules,act_instant}, features/feed |
| E16 Аудиомониторинг отделения и мисселлинг [BRD] | `SA-STT`, `SA-Compliance`, `SA-UI-Compliance`, `SA-TgBot`, `SA-Signals`, `SA-Bench`, `SA-QA` | 13 шт.: T-181…T-193 | app/stt, app/compliance, features/compliance, features/manager, data/corpus/dialogs |
| E17 Режим подстраховки демо [BRD] | `SA-LLM`, `SA-UI-Workspace`, `SA-Agent`, `SA-Infra` | 5 шт.: T-194…T-198 | app/replay, app/demo, app/llm/failover.py, features/demo-menu, install.sh |
| E18 Приём транскриптов, роутер-инструменты, «красные фразы», зоны карты [ДТЗ] | `SA-Agent`, `SA-Prompts`, `SA-Teams`, `SA-Compliance`, `SA-UI-Compliance`, `SA-UI-Workspace`, `SA-Map`, `SA-Signals`, `SA-QA`, `SA-DB` | 15 шт.: T-207…T-221 | app/ingest, app/tickets, app/agent/tools/router_tools.py, app/compliance/batch.py, features/compliance/transcripts, features/tickets, карта «Зоны», migrations/0003 |
| Сквозные v1.3 | `SA-DB`, `SA-UI-Engine`, `SA-Economics`, `SA-i18n`, `SA-Docs`, `SA-UI-Compliance` | 8 шт.: T-199…T-206 | migrations/0002, openapi 1.3, LogPanel, экономика, i18n, демо-скрипт, AGENTS/ADR, «Надиктовать» |

Порядок и волны — в `docs/tasks/README.md` (150 карточек, 6 волн, граф зависимостей, разбивка по слоям и признак «в демо-минимуме»); распределение слоёв по людям — `docs/TEAM-SPLIT.md`. На время спринта до демо порядок задаёт `docs/PLAN-14D.md`: агент выполняет пакет Bxx с указанными урезаниями, остальное из карточек не делает. Критический путь v1.4 (ДТЗ): T-199 → T-221 → T-207 → T-208 → T-210 → T-212 → T-213 → T-214; транскрипты T-219 → T-215 → T-216 → T-217; карта T-207 → T-218; замыкает T-220. Критический путь ядра: T-001 → T-005 → T-006 → T-046 → T-056 → T-057 → T-058 → T-061 → T-062 → T-063 → T-090 → T-142 → T-151. Критические пути контуров BRD: T-005 → T-199 → T-171 → T-172 → T-174 → T-176 → T-177 → T-179 и T-181 → T-183 → T-185 → T-186 → T-187 → T-192; подстраховка T-194 → T-195 → T-198 должна быть готова к первой репетиции. Субагент перед началом читает `AGENTS.md`, `docs/TZ.md` (разделы из карточки), свои контракты и карточку задачи; после завершения заполняет блок «Отчёт» в карточке.

## 10. Чего не делать

- Не добавлять аутентификацию, реальный биллинг, реальные интеграции (в том числе парсинг реальных площадок), TTS и голосовые звонки контакт-центра, голосовую диаризацию на GPU-моделях, локальный запуск LLM, Redis, Kafka, микросервисы, GraphQL. Голос в MVP — только аудиомониторинг отделения и «Надиктовать» через `STTProvider`.
- Не создавать сигналы мимо `app/ingest/normalizer.py`; не заводить таблицу `tickets` или SQLite «тикетницу» — тикет = инцидент; не переименовывать роутер-инструменты и поля `problem_summary` «для красоты» — это внешний контракт заказчика.
- Не двигать деньги мимо `refund_fee` и правил; не публиковать ответы под постами мимо `publish_public_reply`; не хардкодить бизнес-правила в промптах или узлах графа.
- Не подменять результаты распознавания или ответы моделей «заготовками» без пометки режима; mock — последний резерв, replay — основной офлайн-режим.
- Не менять матрицу SLA, доли сегментов, параметры психотипов, ставки dCLTV в коде — только в `data/*.yaml|csv` и через настройки.
- Не «улучшать» формулу экономики и схему психотипов без ADR — они согласованы с бизнес-командой.
- Не писать длинные промпты с примерами реальных банков, брендов, людей.
- Не отключать тесты и линтеры «временно».
- Не делать `git push --force` в `main`; `main` защищён, работа только через PR.

## 11. Куда смотреть при сомнениях

- Требования: `docs/TZ.md`, журнал решений — раздел 20 (решения по BRD — 20.5, по дополнительному ТЗ — 20.6), матрицы покрытия — 0.5 и 0.6, контуры BRD — разделы 21–22 (22.8–22.9 — красные фразы), приёмный слой — 3.7, роутер и тикетница — 9.2 и 9.7; обоснование — `docs/BRD-merge-analysis.md`.
- Схема данных: `contracts/db/schema.sql` (комментарии к таблицам), ER-описание — ТЗ 13.
- API: `contracts/api/openapi.yaml`; локально Swagger UI на `/docs`.
- События: `contracts/README.md`.
- Решения архитектуры: `docs/adr/`.
- Что сломалось или работает не так на стенде: `make report` или `GET /api/reports/quality?format=md`, журнал `backend/var/log/app.jsonl` — `docs/REPORTS.md`. Перед тем как чинить «вслепую», агент читает отчёт: в нём указано, где смотреть.
- Вопросы — техлиду в чат команды с указанием номера карточки и раздела ТЗ.
