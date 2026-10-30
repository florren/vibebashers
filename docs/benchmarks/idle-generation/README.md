# T-273: источник фоновой генерации и проверка исправления

30.10.2026. PostgreSQL 16, два чистых изолированных lite-стенда, по 200 клиентов,
APP_ENV=dev, LLM_CHAIN=mock/LLM_PROVIDER=mock. Пользовательская БД не сбрасывалась.
До: main 1f31fc4. После: ветка codex/idle-generation-csi-repair.
Сырые замеры: before.json, after.json; время UTC, счётчики накопительные.

## Воспроизведение

Нужны Docker, Python3, образы до/после и отдельная PostgreSQL16 в сети cx-seed-review.
Контейнер БД cx-seed-review-pg, тестовые DB cx_idle_before/cx_idle_after, пользователь cx.
Пароль cx в скрипте — только для этой локальной одноразовой тестовой БД.
Нельзя направлять seed/reset или pytest в пользовательскую БД.

Для каждой пустой тестовой БД: контейнером соответствующего backend image выполнить
alembic upgrade head, затем python /scripts/seed/run.py --profile lite --clients 200.
Для образа после исправления дополнительно включить оба старых mock-источника:

```sql
update ingest_sources set enabled=true
where code in ('mock_social_polling','review_portal_feed');
```

Запустить наблюдение (имена контейнеров и порты должны быть свободны):

```bash
python docs/benchmarks/idle-generation/observe.py before cx_idle_before cx-idle-before 18800 cx-pulse-backend:before-idle-20261030
python docs/benchmarks/idle-generation/observe.py after cx_idle_after cx-idle-after 18801 cx-pulse-backend:idle-csi-candidate
```

Скрипт фиксирует состояние до startup, 120 секунд idle; start(speed=60), 15 секунд
работы, pause и 120 секунд; restart backend и ещё 120 секунд. Без внешних запросов.
SQL замера находится в observe.py; точечная проверка происхождения:

```sql
select st.running,st.current_run_id,st.sim_time,r.kind,r.status
from sim_state st left join sim_runs r on r.id=st.current_run_id where st.id=1;
select source_code,count(*) from ingest_messages group by source_code;
select s.origin,count(*) from agent_runs a join signals s on s.id=a.signal_id group by s.origin;
select event_type,count(*) from sim_events group by event_type;
select count(*) from signals s where s.origin='polling'
 and s.external_contact->>'nick'='mock_feed' and s.text like 'Сообщение mock-ленты #%';
```

## Результаты

До исправления до startup: 800 сигналов, 0 событий/постов/agent_runs.
За idle 120 секунд: +100 сигналов, +100 событий, +100 постов, 0 agent_runs.
Состояние: running=false, текущий baseline completed, сим-время неизменно.
За pause 120 секунд: +95/+95/+95/0. После restart зафиксированы уже 52 agent_runs,
из них 50 связаны с polling, два — со штатной симуляцией. Рост продолжался при
running=false (полные отметки времени и промежуточные числа — before.json).

После исправления оба mock-источника принудительно enabled=true.
Idle 0/60/120: 800/0/0/0; start: 802/38/0/2.
Pause 0/60/120 и restart 0/60/120: неизменные 802/38/0/2.
Порядок чисел: signals/sim_events/external_posts/agent_runs. Ни одного polling-входа.
Resume на том же run_id=2 за 15 секунд: operations 2210→2238, events 38→69,
сим-время 06:15:30→06:31:00 UTC, polling=0; затем pause. См. resume.json.
Это короткое окно не обязано содержать сигнал: вероятностный штатный генератор
уже создал два сигнала при start; автоматический тест повторяет два часа с fixed seed.

## Причинная цепочка и требования

main.lifespan запускает polling_worker независимо от часов. poll_source раньше всегда
строил пять _mock_batch сообщений, игнорируя config.url/corpus/batch. normalizer с
emit_event=false подавлял только signal.received, но писал signal + NOTIFY signals;
создание external_posts добавляло review.posted. NOTIFY → realtime → WebSocket/UI
объясняет появление в интерфейсе; работающий LISTEN сам по себе ничего не генерирует.

AgentService._recover выбирал 50 new текущего запуска за последние два сим-часа.
При замороженном времени synthetic polling попадал в это окно и запускал LLM/действия
после restart. Дополнительно recovery менял processing и запускал due followups/HITL.
Проверены отдельными регрессиями реальный live-вход и fake legacy callbacks.

TwinService реагирует на новые клиентские/публичные уведомления с client_id и
завершённым source agent_run; watermark исключает старые уведомления. Автономного
входа в чистом idle не даёт. _abs_backfill — идемпотентное восстановление недостающих
счетов/ledger и пересчёт баланса с emit=false; не создаёт signals/events/posts/AR.
На старых данных может дополнить ledger и audit, это отдельная штатная операция.

ТЗ 3.7/4.6–4.7, BRD live-сценарии и AGENTS 6.1/6.10 различают симуляцию и настоящий
вход. config.url/corpus были незавершённой заглушкой, а не детерминированным
генератором по SimClock. World уже содержит social/review-генерацию. Решение и
явное исключение для mock описаны в ADR-0019. Live HTTP при NULL исправлен отдельно
с согласования пользователя (#105), без старта часов и смены существующих контекстов.

Все три профиля lite/demo/stress проверены автоматическим worker-тестом с enabled=true;
длинные реальные окна измерены только для lite. Финальные результаты полного прогона
и проверки сохранности пользовательской БД прикладываются к PR после выполнения.

На приватной копии актуальной БД стенда (403 MB): 105796 прежних сигналов,
471618 audit-строк, 85 таблиц. Dry-run: 440/480, запись: +40 CSI → 480/480,
повтор: +0. Digest всех прежних строк всех 85 таблиц совпал (settings.coverage
исключён как целевое изменение, в append-таблицах сравнивается прежний префикс).
Решения, ledger, sim_state и seed_done сохранены. См. csi-copy.json.

Пример после исправления: agent_runs id=1/2, SIG-000801/000802, sim_run_id=2,
outcome=completed. sim_events после resume: op.succeeded=62, signal.received=2,
sla.tick=2, по одному client_error.fee_misread/missed_payment/wrong_details.

## Локальные проверки итоговой ветки

`DATABASE_URL_TEST=postgresql+psycopg://cx@127.0.0.1:55434/cx_idle_test make lint test`:
Ruff check/format, mypy (231 source files), OpenAPI drift (186/186), contracts (42 схемы,
158 путей) — успешно. Unit: 588 passed/17 skipped; integration: 137 passed/2 skipped;
scenarios: 22 passed/2 skipped. Дополнительно `pytest -q tests/compliance`: 31 passed.
Всего backend: 778 passed/21 skipped. Пропуски optional/live проверок не заменяют
длинные PG16 окна и обязательные mock-регрессии выше. Существующие предупреждения:
Starlette/httpx deprecation и незарегистрированная метка live в сценарном тесте.
Frontend: ESLint, tsc, 132 Vitest, обе Vite-сборки и отсутствие diff после gen:types
успешны. i18n: 1416 ключей; owners --allow-cross; git diff --check — успешно.

Coverage.py 7.17 (временный инструмент вне зависимостей проекта): 26 регрессий
под coverage + read-only CLI dry-run. Новые исполняемые строки diff: 162/185 =
87,57%, включая scripts/seed/repair_csi.py; это покрытие добавленных строк, не всей
кодовой базы. Развёрнутые числа и непокрытые строки — coverage-diff.json.
