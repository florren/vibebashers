# Предфризовая проверка 04.11.2026

Фриз: 05.11.2026 в 06:00 МСК. Локальный gate завершён: `make test` PASS (exit0), `make lint` PASS.
Финальные CI и human review фиксируются в PR; merge допускается только после
зелёных обязательных checks и подтверждения границы транзакций.
Весь первоначальный backlog и 100% покрытия проекта этим документом не объявляются завершёнными.

## Проверенный код и локальные gates

Основа main: `7fe3f85f2a2223ccdd016dfaf72f7de44aa55ecc`.
Полный literal `make test` выполнен на неизменном `ac6fcc53ac4208b0221517a739f9f6371922d635`,
с собственной PG16, Node22.23.4, mock LLM/TG, настоящей локальной моделью Vosk
и built frontend из image `sha256:29da5664fb1f61b26713045b6efdece473796e3e883f0e5c0864ea31cec61da8`.
Сверены engine/API/LLM исходники image и checkout; HEAD и все трекнутые файлы до/после команды совпали.
После этого меняется только финальная документация; продуктовый код и тесты те же.

- Backend unit:2269 passed /19 skipped.
- Backend integration:913 passed.
- Scenarios:43 passed /2 skipped.
- Compliance:31 passed.
- Frontend:591 passed /82 test files.
- Telegram bot:50 passed.

Всего в этой команде:3897 passed /21 skipped.19 skips — отсутствие schema examples;
ещё2 — live latency без credentials и отсутствие настоящей replay11 cassette.
Существующие Alembic path_separator deprecation warnings не подавлялись.
Для bot stage до его начала задан explicit current-source import alias:
общий editable venv указывал на прежний worktree. Все5 bot Python files сверены
с текущим checkout; production/test source и assertions не менялись.

Новый полный frontend после cache regression: **591 passed / 82 files**.
`make lint` passed: Ruff/format, strict mypy329 backend/5bot files, ESLint/TypeScript.
Contracts48 schemas/167paths; OpenAPI drift197=197, missing/extra0; i18n2326 keys;
licenses550backend/36bot — passed. Owners L1–L5: разрешённый cross-layer,
`check_owners.py --base main --allow-cross` passed. Diff/secrets-pattern check
и визуальный review synthetic screenshots пройдены; приватные данные в Git не включены.

## Исправленные дефекты

- Shared simulator connection: preflight/control/final commit и baseline dump
  согласованы с native tick lock; baseline повторно проверяет status после ожидания.
- Target advancement пересчитывает remaining под lock; concurrent Stop не создаёт
  новый run, Pause→Start сохраняет resume hooks, guard-row handoff не deadlock.
- Personal history использует фактический `sent_at`, а не начало старой TX;
  legacy без sent_at сохраняет прежний fallback. Старые записи не переписываются.
- SMTP tracking receipt получает фактическое время успешной отправки.
- CLI baseline reset требует explicit opt-in; timeout/failed не выдаются за PASS.
  CI PROFILE соответствует seed; API guards сохранены.
- OpenRouter missing usage сохраняет только bounded safe generation reference;
  unknown/caps/fallback/billing policy не меняются. Старый потерянный ID не восстановлен.
- LiveMeeting обновляет badge только по текущему server closed; Close доступен при320px.

Test-only дефекты исправлены без ослабления assertions: wire query больше
не выбирает чужой historical credential/scope, cabinet e2e не ждёт HTTP для
законного fresh Query cache. Добавлены foreign-wire и warm-cache regressions.
Старые неудачные результаты сохранены отдельно, не переписаны в passed.
Предыдущий полный integration на aa3ab873:912passed/1failed из913; единственный
сбой — старый SimpleNamespace без штатного `_lock`. Добавлена одна строка в fixture,
все legacy/actor/marker/RNG/secret/no-dump assertions сохранены:RED1→GREEN1,
полный runtime_profiles32passed. Затем выполнен новый полный literal make test.

## Runtime, UI и хронология

- Fresh corrected nightly на том же image: **168/168** browser cases
  (150read/settings +13native scenarios +5inputs), ru/en и обе темы.
  Demo5000 wall seed24.31s; пять API p95≤49.52ms, violations=[].
  Первоначальные143/7 привели к cache root cause; controlled UI/API proof и
  21focused cases прошли до полного fresh повтора. Timeout не увеличивался.
- Native catalog35:5strict declared checks,6partial-with-unknown,20smoke;
  4not_verified(12/13/34/35). Repeats17/26×2 passed;409/drain/scope/clock errors0.
  Это не35 полностью подтверждённых acceptance.
- 21native personal→PG NOTIFY→WS samples: p95=17.473ms,max23.526ms.
- Actual built personal UI на отдельном public origin/PG: старая TX началась
  до browser question; answer.at==sent_at, DOMquestion→bank, errors/external0.
  Реальные POST/GET/notify_client, без API mocks; ответ synthetic worker, не LLMgraph.
- Отдельный graph→TwinService→child graph regression: paused/+1simhour,
  пять wall и пять sim timestamps, lineage/idempotency и ненулевые twin counters.
- Fresh native SQL:381notifications/2public replies/1gift без известных инверсий;
  у1chat неизвестен исходный вопрос, child/twin0 — эти ветки закрыты отдельно.
- Read-only primary:331reactions/54twin-child/60childsignals/580public replies
  и восемь сохранённых каналов без инверсий вопрос/ответ. Общий all-runs audit
  сохраняет одну старую gift sim-time инверсию от01.11 в interrupted run доPR213/214.

## Live LLM и внешняя доставка

Согласованный ограниченный прогон выполнен один раз:13inference+8service HTTP,
затем1read-only OpenRouter/key; только fixed synthetic context, TLS, no provider fallback.
- Резервный GigaChat: обе normalize/classify/decide цепочки live+ok,6known attempts,
  собственные answers/Journey без инверсий — passed.
- Основной GigaChat:6known attempts и два ответа; один decide отвергнут schema
  при одной разрешённой попытке, затем safe deterministic policy. Это degraded,
  не полностью live PASS. Первичный слишком мягкий harness result исправлен
  ручным review checkpoint; raw result сохранён.
- OpenRouter: первый response без usage → unknown; следующие calls запрещены
  до HTTP. USD0 не доказывает tokens0. Для reconciliation нужны provider facts;
  unknown не очищался, ключ остаётся blocked. Runtime не зависит от Studio/browser.

Две реальные Telegram доставки прошли native notify/outbox/claim/send/ack только
приватно проверенному разрешённому self. Отдельно настоящий pending `/start`
прошёл aiogram→HMAC→backend→outbox→sendMessage→ACK:3metadata HTTP,1greeting,
1durable receipt/no resend, offset не продвигался, другие updates не импортировались.
Readiness/QR проверены cold503→proof200→stale/stop/restart503 и4browser cases.
Primary worker не включался. Generic notify_client(email) виртуален; настоящий
local SMTP sink проверял tracking receipt success/privacy/no-resend и550→failed,
не внешнюю почтовую доставку/Mailpit.

## Recovery, audio и покрытие

- Full dump/restore DDL0021:115tables/60sequences/DDL/ACL/owners/comments exact,
  ledger MAC valid. Восстановлены22known/2reconciled/1unknown. На network=none clone
  actual PostgresAccounting запрещает admission до ticket; все runtime hashes
  и sequences после проверки unchanged, HTTP/inference/reconciliation0.
  Private backup0600; env/config recovery копия0700dir/0600files внеGit.
  Host/assets и HITL resume этим full-DR read-only proof не объявляются проверенными.
- Chrome fake WAV microphone→AudioWorklet→PCM16→Vosk прошёл personal и compliance:
  draft без autosend,14partials/2finals, closed report,0external speech/LLM.
  Физический микрофон и отдельный partial-latency SLA не подтверждены.
- Единый final engine main→221654 trace:84/99 executable AST statement starts
  (84.85%),24native cases passed;15missed перечислены в source-qualified JSON.
  Baseline producer8/8, personal changed executable lines2/2, OR reference13/13;
  методы/границы описаны в reviews. Это не branch или full-project coverage.

## Оставшиеся ограничения

OpenRouter blocked до подтверждённой сверки; один GigaChat output degraded.
Replay11 cassette отсутствует; live latency benchmark без credentials пропускается
в offline suite. Четыре catalog acceptance не закрыты самим native checker.
`/api/public/mock-social-feed` и `/api/signals/{id}/normalized` остаются явными501
и не объявляются реализованным/протестированным функционалом. Старые failed runs,
checkpoints и timestamps автоматически не исправляются.

Reviews: [engine transaction](freeze-sim-control-serialization.md),
[target/resume](freeze-sim-target-control.md),
[combined coverage](freeze-final-engine-combined-coverage.md),
[baseline](baseline-shared-connection-2026-11-04.md),
[personal](freeze-personal-delivery-clock.md),
[SMTP](freeze-tracking-smtp-clock.md),
[CLI](freeze-scenario-checker-2026-11-04.md),
[OpenRouter](T-048-openrouter-recovery-reference.md),
[LiveMeeting/screenshots](live-meeting-closed-status-2026-11-04.md),
[cache](cabinet-preview-cache-e2e.md).

Новых API/DDL/event schemas нет. Формулы, ставки, суммы, лимиты и HITL полномочия
сохранены. Откат после остановки runtime — прежний backend/personal image;
миграций нет, история не переписывается. Откат возвращает исправленные гонки.
