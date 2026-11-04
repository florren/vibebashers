# Предфризовая проверка 04.11.2026

Статус: проверка выполняется. Фриз — 05.11.2026 в 06:00 МСК.
Основа приложения: main `7fe3f85f2a2223ccdd016dfaf72f7de44aa55ecc`.
Этот документ не объявляет весь исходный backlog завершённым.

## Повторные проверки текущей версии

- Backend unit итогового v3: 2269 passed, 19 skipped; причины всех 19 — `нет examples`
  у схем. Отсутствие примера не доказывает проверку соответствующего поведения.
- Frontend итогового v3: 590 passed, 82 test files, Node 22.23.4.
- Telegram transport: 50 passed, fake HTTP, без внешних сообщений.
- Ruff check/format: passed; mypy: 329 source files, no issues.
- Frontend lint/typecheck: passed.
- Contracts: 48 схем, 167 путей; OpenAPI drift: 197 операций в spec/code,
  missing=0/extra=0; i18n: 2326 ключей, passed.
- Полный PG16 suite с twin-регрессией: 3175 passed / 21 skipped, 3196 tests /
  305 modules; четыре отдельных checkout/PG16 на `322229d`, union manifests passed.
  Skips: 19 без examples, один live latency без ключей, один replay сценария11.
  Vosk WAV прошёл с существующей локальной моделью.
- После объединения исправлений: весь unit suite 2269 passed / 19 skipped;
  отдельно 77 CLI/CI-helper unit, 21 SMTP/twin/tracking/chronology PG,
  51 OpenRouter/accounting/checkpoint PG, 5 serialization PG + 72 composition PG.
  Полный финальный CI и повтор native/browser-проверок ещё обязательны.

## Расширенный nightly

Изолированный Compose, образ с тем же деревом приложения, synthetic demo/5000,
mock LLM, выключенная внешняя доставка. Seed — 23.922 s; активная симуляция,
21 GET на каждый endpoint, nearest-rank p95: health 23.22 ms, sim/state
11.30 ms, signals 26.02 ms, map/heat 43.05 ms, dashboard 40.07 ms.
Violations: []. Лимиты 90 s / 300 ms не менялись.

Полный browser suite: 150 read-only/settings + 13 native scenarios + 5 inputs
= 168 passed. Проверены языки, темы, мобильные размеры и отдельный personal
origin. Это mock-приёмка; реальная LLM не подразумевается.
Первый browser запуск не нашёл Chromium в стандартном cache; повтор с имеющимся
headless shell 1217 прошёл. Первоначальный сбой окружения не считается product fix.
Первый harness использовал PROFILE=lite при seed demo: измерения 5000 клиентов
действительны, но baseline был недоступен. CI helper исправлен, обе конфигурации
покрыты unit-тестами; повтор на f297480 прошёл:168 browser cases, PROFILE=demo, baseline_available=true, seed24.85s; все пять API p95≤48.39ms, violations=[]. Новый итоговый v3 требует собственного повтора.

## Хронология

Новая регрессия `test_freeze_twin_chronology.py` прошла два случая на собственной
PG16: paused и +1 sim-hour. Production graph создаёт ответ банка, TwinService
создаёт реакцию и дочерний сигнал, production graph создаёт следующий ответ.
Проверены пять wall-clock и пять sim timestamps, run lineage, идемпотентность,
ненулевые reaction/twin-child counters и отсутствие инверсий в SQL audit.
Управляемый mock задаёт только LLM-решение asks_again; дочерние эффекты не подделаны.

Read-only аудит рабочего localhost: 331 реакция, 54 twin-child, 60 дочерних
сигналов и 580 публичных ответов — без инверсий относительно предшествующего
сообщения. Во всех восьми сохранённых каналах также ноль инверсий вопрос/ответ.
Общий all-runs audit остаётся false: одна историческая gift-инверсия от 01.11
в interrupted run, до исправлений PR213/214. История автоматически не менялась.
Эти проверки доказывают сохранённые timestamps, а не качество смысла или доставку.

## Telegram: настоящая доставка

Разрешённый пользователем адресат проверен приватно; другие получатели исключены. Два ограниченных
сообщения отправлены через штатные notify_client/outbox/claim/TelegramClient/ack
на собственной synthetic PG16. Telegram API подтвердил обе отправки; получены
два durable sent receipts. Проверены HMAC401, duplicate idempotency, conflict409,
client grant, отсутствие повторной отправки и wall/sim порядок вопрос/ответ.
Primary settings/worker/DB не менялись. Вход был синтетическим подписанным
service event; это не доказательство свежего сообщения через aiogram dispatcher.

Отдельная readiness-проверка использовала настоящий aiogram SDK: один GetMe,
один GetUpdates без offset, затем HMAC heartbeat и остановку до feed_update.
Реальный delivery worker с запретом egress не отправил ни одного сообщения.
QR проверен 503 → 200 → 503 после 90 секунд/остановки/restart без нового proof.
Четыре browser cases ru/en, desktop/mobile, light/dark прошли без page errors.
Число SDK-вызовов ограничено двумя; redirect hops выполненный harness отдельно
не измерял. Полный dispatcher input этой проверкой не заявляется.

## Полное восстановление populated БД

Новый полный pg_dump без фильтров схем восстановлен в отдельную PG16 без сети.
Один экспортированный READ ONLY REPEATABLE READ snapshot: совпали содержимое
115 таблиц, 60 sequences (стабильны во время snapshot), полный DDL/ACL/comments
и extensions pg_trgm 1.6, pgcrypto 1.3, plpgsql 1.0.

Сохранены 12 wire attempts: 10 known / 2 reconciled, четыре reconciliations,
один app-origin GigaChat, credential/profile accounting. Проверка identity MAC
с исходным APP_SECRET прошла; registry ciphertext отсутствует, поэтому проверка
его расшифровки неприменима. Пять read-only API на clone вернули 200 при
transaction_read_only=on, APP_ENV=test, без lifespan/workers.

Operational channel tables в этом snapshot пусты, unknown/reserved attempts нет.
Проверка их аварийного восстановления остаётся отдельными fault-регрессиями.
Это не проверка HITL resume, host config/assets или внешних вызовов на clone.
Приватный полный backup 178795217 bytes сохранён отдельно с mode0600;
вызовов LLM/admission/reconciliation на скопированном ledger не было.
Selective backup operational schema не заменяет полный backup для чистого кластера:
для full DR нужны extension metadata, APP_SECRET и конфигурация вне dump.

## Live LLM: ограниченный согласованный прогон

Это instrumented API/graph acceptance отдельных synthetic банков с общим
canonical operational ledger; untouched production browser E2E не заявляется.
Два фиксированных анонимных обращения на источник, без реальных данных банка,
TLS включён, без model/provider fallback. Studio не используется.

Фактически 13 inference HTTP и восемь служебных HTTP; после остановки выполнен
один read-only GET OpenRouter /key. Весь harness не повторялся.

- Основной GigaChat: два собственных ответа/Journey, ноль инверсий, шесть known
  attempts. Первый decide отвергнут схемой при одной разрешённой попытке;
  далее сработала безопасная детерминированная политика. Это degraded, не PASS
  полностью live цепочки.
- Резервный GigaChat: обе цепочки, normalize/classify/decide live+ok,
  собственные ответы/Journey, ноль инверсий, шесть known attempts — passed.
- OpenRouter: первый ответ без usage, попытка unknown; последующие вызовы
  заблокированы accounting до HTTP. Observed0 не является доказанным расходом0.
  GET /key USD=0/free requests=4 не устанавливает токены. Старый adapter потерял
  generation ID; для reconciliation нужны подтверждённые данные провайдера.
  Unknown вручную не очищался.

Первичный private harness слишком мягко оценил основной GigaChat по наличию
live шагов, пропустив error с source=NULL. Ручная ревизия checkpoint/trace
исправила итоговую оценку; сырые результаты сохранены и не переписаны в passed.

## Подтверждённые исправления и дополнительные проверки

- SMTP receipt: wall-clock вместо начала транзакции. Обычный public claim
  отдельно прошёл; старую TX-инверсию воспроизвёл regression. Настоящий local
  SMTP sink подтвердил MIME/privacy/no-resend и SMTP550→failed. Это не Mailpit:
  его image отсутствовал. Общий notify_client(email) остаётся виртуальным;
  SMTP реализован для tracking receipt.
- CLI: baseline только с явным opt-in, без него zero POST; timeout и failed/error
  больше не выдаются за PASS; PROFILE CI совпадает с seed. API guards сохранены.
- Simulator: control preflight/reset_day policy-read/final commit сериализованы
  с native tick. RED5→GREEN5, ещё72 PG, новые executable statements90%
  (консервативный raw AST85.71%). Human review общей tick TX обязателен.
- OpenRouter: безопасные bounded generation ID/provider code сохраняются
  в существующей диагностике/checkpoint; raw messages/headers и секреты не
  выводятся. Unknown, caps, fallback и billing policy не меняются. Потерянный
  старый ID ретроспективно не восстанавливается. 19 новых unit / 4 новых PG passed.

Все восемь прежних positive-GET gaps проверены на собственной fresh PG:
benchmark detail/export, compliance session/utterances/report, ingest transcript,
public track и settings export — 200 с проверкой содержимого. Export body
не печатался и не сохранялся. Primary данные/настройки не менялись.

На f297480 повтор native каталога:31 из35 declared results true,0 control/tick409; четыре read-model/UI/replay acceptance остаются not_verified. После каждого write:active AgentRuns0, failed0. Native personal→PG NOTIFY→operator WebSocket:21 samples, p95=8.502ms, max=14.261ms; это bounded sample, не длительный нагрузочный benchmark.

## Оставшиеся проверки и границы

- После объединения исправлений нужны exact-head полный CI, повтор nightly
  и native-каталога; сериализация tick требует финального human review.
- OpenRouter остаётся unknown/blocked до сверки; основной GigaChat имеет один
  отклонённый model output в ограниченном тесте. Это не all-live PASS.
- Vosk проверяется существующей локальной моделью и WAV; физический микрофон
  и внешние speech-сервисы этим не подтверждаются.
- Replay-кассеты сценария11 нет; mock не заменяет этот acceptance.
- В native каталоге четыре случая не закрыли recorded read-model/UI/replay acceptance; smoke/unknown не считаются доказательством полного поведения.
- `/api/public/mock-social-feed` и `/api/signals/{id}/normalized` остаются явными
  501; не входят в реализованный функционал и не объявляются passed.

Приватные dumps, исходные сообщения, ключи, ledger и сырые логи в Git не включаются.
Финальное решение по фризу принимается после завершения проверок и зелёного CI
с новым regression, с явным перечнем оставшихся ограничений.

## Итоговый v3: дополнительные исправления и текущий gate

- Финальный target/resume diff описан в `freeze-sim-target-control.md`:23 адресных
  и72 composition PG passed;69/79 новых executable statements (87.34%). Исправлены
  overshoot reset_day/jump_to, stale Pause/Start/demo status и guard-row deadlock.
  Допустимое первое создание implicit run и Stop между chunks покрыты отдельно.
- Baseline dump удерживает тот же simulator lock с повторной проверкой status:
  RED4→GREEN24;8/8 новых producer statements выполнены. Подробности и откат —
  `baseline-shared-connection-2026-11-04.md`. Human review общей tick TX обязателен.
- Compliance LiveMeeting обновляет badge только по текущему server closed; stale
  socket игнорируется. Close помещается при320px. Production Chrome:4 status и8
  responsive cases ru/en×themes; component tests и итоговые590 frontend passed.
- Настоящий WAV→Chrome AudioWorklet→PCM16→Vosk прошёл personal и compliance:
  draft без autosend,14 partials/2 finals и closed report; внешний STT/LLM0.
  Использован fake microphone из WAV; физический микрофон и partial latency SLA
  этим не подтверждены.
- Полный literal `make test` на f297480:unit2269 passed/19skipped, integration
  881passed/3failed; следующие make targets не запускались после ошибки. Причина
  трёх ошибок — тест выбирал чужой historical wire по reused numeric profile_id.
  Test-only fix bcfcf15 проверяет physical credential и текущий quota scope,
  намеренно сохраняя foreign wire:RED3→GREEN4, accounting→recovery→OR51passed.
  Это не production fix и не основание считать прежний make test зелёным.
- Полный итоговый v3 make test и exact-head CI ещё обязательны. До них статус
  проверки остаётся открытым; merge и rollout не объявлены выполненными.

Отдельная bounded real-poll проверка завершилась PASS: GetMe/GetUpdates/GetChat
(3 actual metadata HTTP), настоящий private self `/start` отфильтрован до
aiogram Dispatcher, native HMAC→backend→outbox→sendMessage→ACK. Ровно одно
штатное приветствие и durable sent receipt; повторная deliver_once без отправки.
Offset не продвигался, другие updates не импортированы, signals unchanged, LLM0.
Redirects/retries запрещены на фактическом HTTP boundary, TLS включён. Это
инструментированная single-iteration проверка, не включение primary worker.

На итоговом v3 `make lint` passed (включая frontend590 tests, strict mypy329
backend/5 bot source files); contracts48/167, drift197=197, i18n2326 и licenses
550backend/36bot passed. Обычный owners check сообщает L1/L2/L3/L4; cross-layer
пакет ранее разрешён пользователем и проверяется явным --allow-cross.

Повтор full DR после live также PASS:новый экспортированный read-only snapshot
115таблиц/60sequences/DDL/ACL/owners/comments exact;22known/2reconciled/1unknown
сохранены, ledger MAC с исходным APP_SECRET valid. Production PostgresAccounting
на network=none clone запрещает key_scope admission до ticket:quota/operator
reconciliation. После проверки все llm_runtime hashes и60sequences unchanged.
Provider/HTTP/inference/reconciliation не создавались. Backup178796010bytes,0600;
env/config/assets отдельно, registry ciphertext rows0. Primary только читалась.

Независимое review обнаружило ещё Stop-before-first-target-chunk: после уже
подтверждённого Stop target мог создать новый free run. Native HTTP RED2/2
воспроизведён; допуск initial implicit owner теперь фиксируется под preflight
lock. GREEN24cases155.72s,6/6 новых executable statements выполнены. После stale409
независимое DB соединение проверяет сохранение exact run/time/RNG/stopped.
Исходно inactive/None owner по-прежнему допустим. Новый engine SHA256:
2216549050deef94a579103a2a9cb6a66926c1653b720cb70cf1a21b48451679.
Ruff/format/mypy этого addon прошли; итоговый make test ещё обязателен.

## Final personal projection и повторные gates

Read-only review выявило реальный personal9999 дефект:answer.at использовал
notification.created_at (начало старой транзакции), хотя фактический sent_at был
после question.received_at. Native POST/GET+notify_client RED1failed10.54s.
Теперь projection берёт coalesce(sent_at,created_at); DTO/DDL/история сохранены,
legacy без sent_at остаётся fallback, недоставленные statuses не показываются.
GREEN26PG185.17s:6новых channels/filter/legacy+3personal+15channelchronology+2twin.
Instrumented6cases:2/2 изменённых executable lines; это не branch/full coverage.
Review:`freeze-personal-delivery-clock.md`, personal.py SHA256:
aec37946f973223561fc95122252eb0f09456f463e259c936323a1a58ddbbf27.

Последний v3 engine221654 composition70passed541.02s. Pinned v3 image
92aae266 завершил150read/settings+13scenarios+5inputs=168browserpassed; demo5000
seed23.53s,p95API≤44.74ms,violations=[]. Personal projection требует нового v4
image повторного browser gate; v3 evidence не объявляется доказательством этого fix.

Literal make test на9af4bc7 остановился в unit:2267passed/2failed/19skipped.
Причина окружения private QA driver:blank LOCAL_LLM_API_KEY и TGBOT_ENABLED=false
перекрывали fixture Settings(_env_file=...). Product/assertions не меняются; новый
запуск убирает optional secret/enable overrides, сохраняя mock/ownDB/ENV_FILEdevnull.
Старый результат сохранён; новый full make test/CI остаётся обязательным gate.

## Финальный v4 runtime и test-only cache correction

- Final v4 engine/personal source проверен в image29da5664 и aa3ab873.
  Полный35native catalog:5 strict declared checks,6 partial-with-unknown,20smoke,
 4not_verified(12/13/34/35); повторы17/26×2passed,409/drain/scope/clock errors0.
  21personal→PGNOTIFY→WS:p95=17.473ms,max23.526ms. Own SQL:381notes/2public/1gift
  без известных инверсий; у1chat неизвестен исходный вопрос, child/twin0.
  Отдельные26PG/twin tests выше закрывают соответствующие ветки, не этот каталог.
- Actual personal browser на imagev4 прошёл oldTX schedule:created_at до
  browser question; GET answer.at==sent_at; DOMquestion→bank,errors/external0.
  Настоящие builtUI/POST/GET/notify_client, без APImocks; bank reply в synthetic
  worker, LLMgraph этой display-проверкой не заявлен.
- Первая полная v4 browser попытка:143passed/7failed. Cabinet test ожидал новый
  HTTP для уже свежего regional cache (staleTime5000); корректный UI показывал
  серверную сумму. Timeout мешал cleanup и загрязнял settings для следующих5.
  RealQueryClient regression и actual UI/API подтвердили cache hit без HTTP;
  test-only distinct manual input сохраняет money/response assertions и добавляет
  affected_count equality. Production code, timeout и финансовые формулы сохранены.
  21focusedpassed; новый fullfrontend591passed и make lint passed.
- Полный fresh corrected v4 nightly:150read/settings+13scenarios+5inputs=168passed.
  Seed5000 wall24.31s, пять API p95≤49.52ms,violations=[]. Старый143/7 сохранён.
- Literal make test на aa3ab873:unit2269passed/19skipped; integration ещё идёт.
  Во время команды checkout/HEAD не меняются. Новые cache tests/docs находятся
  отдельно от этого immutable checkout; новый fullfrontend591 уже проверяет их.

Приватные runtime config/env recovery copies сохранены0700dir/0600files внеGit.
Primary read-only health8000/personal9999=200; merge/rollout ещё не выполнены.
