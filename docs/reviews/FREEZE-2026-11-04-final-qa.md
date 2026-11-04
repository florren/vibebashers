# Предфризовая проверка 04.11.2026

Статус: проверка выполняется. Фриз — 05.11.2026 в 06:00 МСК.
Основа приложения: main `7fe3f85f2a2223ccdd016dfaf72f7de44aa55ecc`.
Этот документ не объявляет весь исходный backlog завершённым.

## Повторные проверки текущей версии

- Backend unit: 2229 passed, 19 skipped; причины всех 19 — `нет examples`
  у схем. Отсутствие примера не доказывает проверку соответствующего поведения.
- Frontend: 583 passed, 81 test files, Node 22.23.4.
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
покрыты unit-тестами; повтор nightly ещё обязателен.

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

Native personal→PG NOTIFY→operator WebSocket: 3.076ms, один sample;
это не длительный p95/нагрузочный WS benchmark.

## Оставшиеся проверки и границы

- После объединения исправлений нужны exact-head полный CI, повтор nightly
  и native-каталога; сериализация tick требует финального human review.
- OpenRouter остаётся unknown/blocked до сверки; основной GigaChat имеет один
  отклонённый model output в ограниченном тесте. Это не all-live PASS.
- Vosk проверяется существующей локальной моделью и WAV; физический микрофон
  и внешние speech-сервисы этим не подтверждаются.
- Replay-кассеты сценария11 нет; mock не заменяет этот acceptance.
- До serialization fix из35 native cases: 29 passed (5 полных declared checks /
  6 с unknown / 18 smoke), два control/tick409; ещё четыре не закрыли recorded
  read-model/UI/replay acceptance. Повтор не должен превращать smoke/unknown
  в доказательство полного поведения.
- `/api/public/mock-social-feed` и `/api/signals/{id}/normalized` остаются явными
  501; не входят в реализованный функционал и не объявляются passed.

Приватные dumps, исходные сообщения, ключи, ledger и сырые логи в Git не включаются.
Финальное решение по фризу принимается после завершения проверок и зелёного CI
с новым regression, с явным перечнем оставшихся ограничений.
