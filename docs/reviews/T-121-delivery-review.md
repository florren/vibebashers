# T-121: durable Telegram transport — checkpoint для review

Реальных Telegram HTTP, getMe или сообщений людям не было. Пользователь разрешил
service-to-service HMAC, но final API/DDL review и live smoke этим не заменяются.
Статус: реализация и source-qualified полный local proof готовы; final review/CI перед merge. Последний итог — внизу и T-121-final-verification.json.

## Контракт и совместимость

OpenAPI1.5.20: **все** kinds internal inbound требуют bot_id/update_id и точную
HMAC-SHA256 подпись version/timestamp/method/path/body hash, окно ±60s, body≤32768.
Middleware проверяет до Pydantic/DB: 401 invalid signature, 413 oversized, 503 disabled
или неполная конфигурация; 422 invalid DTO, 409 duplicate identity с другим payload.
Bot/backend обновляются вместе. Старый unsigned или без-ID caller несовместим.

0015 после actual0014 добавляет notification.delivery_key UUID и status unknown;
6 private channel_runtime tables: conversations, inbound updates, deliveries,
chat rate, signal bindings, client bindings. Private schema исключена из банковского
baseline, без FK на resettable public. Payload/state/response шифруются APP_SECRET.
Signal grant связывает chat с run/signal/tracking token hash; client grant требует
явный /bind и актуальный synthetic code. Seed chat IDs не являются разрешением.
Старый ID после reset не прикрепляется к новому объекту автоматически.

## Доставка и границы

Signed inbound фиксирует диалог, notification queued и encrypted outbox одной TX.
notify_client для enabled Telegram тоже создаёт queued, не выдумывает Sent/external_ref.
Fake/offline channels сохраняют существующую эмуляцию. JSON agent schema не менялась.
Все tracking capabilities скрыты в публичном body, wire payload остаётся private.

Worker фиксирует admission **до** HTTP, держит bot session advisory lock, shared
run lease и существующую cross-process maintenance/public writer границу до finalization;
DB row lock не удерживается во время HTTP. Per-chat rate =1 admission/real second,
другие чаты не блокируются очередью первого. Единственный TLS sendMessage без скрытых
retry/redirect; timeout15s, bounded response64KiB, strict chat/message identity.
Ack→sent +actual external_ref/sent_sim/sent_at; definite rejection→failed;
network/timeout/cancellation/process death→unknown, **без автоматического resend**.
Оставшийся claimed после crash восстанавливается unknown; restored queued с той же
UUID/hash получает прежний результат. Не обещаем exactly-once внешнего сервиса.

Ошибки worker не останавливают симулятор. Maintenance паркует/перезапускает только
принадлежащую lifespan задачу. Configuration change требует restart. Токены и
upstream description/body/traceback не записываются в notifications или SDK logs.
Manager accept/reject не подключены: T-189 имеет отдельную HITL границу.

## Уже выполненные проверки (до final composition)

-39 signature/actual-ASGI tests, authentication-before-DB/error paths; 34bot fakeSDK/HTTP/CLI/license tests.
-7 legacy/storage PG и3 durable dialogue PG, restart через новый connection/app,
 dedup/conflict/language/stale-binding;6 storage PG включая настоящий PG16 dump/restore.
-12 delivery/dialogue PG за53.54s: committed admission, parallel workers, rate,
 explicit failed/unknown/cancel, restore reconciliation, maintenance/run-delete leases,
 private receipt после удаления run и отсутствие grant у seed.
-1 actual normalizer→Mock graph→queued→fake acknowledgement PG за7.18s.
-1 **owned OS SIGKILL** PG за6.64s: marker после committed claim, kill своего child,
 новый worker переводит unknown, ни одного повторного fake wire вызова. HTTP отсутствует.
-27 lifecycle/client/installer unit за1.99s; bot image построен,
 `--network none --offline` passed; Compose config проверен без чтения/вывода .env.
-Полный unit прежнего inbound checkpoint:1562pass/18skip; это **не** full proof нового worker.

Final-head make lint/test/coverage, UI screenshots и exact-head CI ещё не заявлены.
Frontend unknown имеет отдельный ru/en warning badge; screenshots готовятся.

## Rollback / эксплуатация

0015 forward-only: не удалять receipts, чтобы не повторить отправку. Выключить
TGBOT_ENABLED, остановить profile telegram; другие каналы продолжают работать.
Для восстановления enabled transport вернуть совместимые bot/backend и исходный
APP_SECRET/internal secret. Не откатывать на unsigned inbound поверх включённого бота.
Не выполнять повторную отправку unknown без ручной сверки Telegram. Автоматического
backfill внешних сообщений для прежних seed/history нет. Реальный jury/health/QR
проход остаётся T-122/live proof; health flag+token пока не означает verified liveness.

## Composition P1/current main и повторные проверки

Runtime source155600e содержит P1 profiles/startup guards и main e572939.
Полный backend unit:1633passed/18skip54.20s. Штатный make lint green:
326frontend, Ruff431/mypy283, botRuff11/mypy5, drift192. 87target unit/PG
passed89.80s; весь transport412/450 исполняемых строк=91.56%, delivery130/149=87.25%,
каждый transport module≥80%; hashes в T-121-transport-coverage.json.

Production UI unknown:4/4 ru/en×themes, настоящие API, отдельные явно синтетические
status fixtures (не фактические Telegram receipts),94 table hashes unchanged,
0nonGET/0external/0LLM/pageerrors. Screenshots и proof:docs/screenshots/T-121/.
Preview принудительно default_transaction_read_only, external DNS/socket guard;
собственный процесс остановлен после proof. Обе production builds прошли штатный
npm run build (он уже включает personal); отдельного build:personal script нет.

Полные integration/scenario/compliance/bot фазы ещё выполняются; итог не заявлен.

## Final local proof и parent composition

Полный make test на7acce1b завершилсяexit0:1633unit/18skip,390PG/2skip,
43scenario/2skip,31compliance,331frontend,34bot. Итого2097backend/22skip.
Наcurrentmain501/P1e6→93f180b:1640unit/18skip49.81s, make lint348frontend,
Ruff432/mypy283,botRuff11/mypy5,drift192;15actualPGdelivery/dialogue/public93.85s.
Ancestry-only parentmerge3450afe имееттотжеtree, latestT240cbfd включён.
Это source-qualified verification, не новый монолитный make test на3450afe.

Покрытие ВСЕХ новых backend executable строк относительноactualparentT240:
575/623=92.30%, каждый затронутый runtimefile≥80%; generatedORM исключён,
schema/generator/migration провереныотдельно. 88actualunit/PG106.84s +18ASGI/lifespan
15.64s на техжеruntimeblobs. Bot219statements/209covered95.43%,43fakeSDK/CLI
15.12s: SIGTERM/cancel/sessioncleanup, rate/network/server/permanentpollerrors,
nooffsetadvance и secret-negative assertions. Backendlicense550+bot36green;
botgate запускался bot interpreter (backend interpreter не содержит aiofiles).

ActualnotificationsUI повторён на3450afe:4ru/en×themes,94tablehashesunchanged,
0browsernonGET/external/LLM/pageerrors, новые4PNG/proof сохранены. Previewостановлен.
Ни один файл/результат не утверждает настоящий Telegram smoke или jury QR flow.
Детальные источники/хэши: T-121-final-verification.json, added-backend-coverage.json,
bot-coverage.json и docs/screenshots/T-121/proof.json. Final API/DDL review и
exact-head CI ещё обязательны доmerge; T122actualreadiness/QR остаётся отдельной веткой.
