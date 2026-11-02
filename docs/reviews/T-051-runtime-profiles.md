# T-051 P1: configuration → execution

## Статус

Составная ветка объединяет SDK/main, T-041 maintenance297a8459, P1 API1.5.18/DB0013 и UIa631386. Актуальный main1df0024 подключён ordinary merge с сохранением DB и Compare tabs, golden corpus/RNG и legacy migration comments. Первый полный прогон имел2 подтверждённых отказа; они исправлены в отдельном control/fixture checkpoint, targeted проверки проходят. Полный итоговый прогон/coverage/CI и human review ещё впереди. Исторические числа ниже привязаны к конкретным checkpoint и не объявляются доказательством нового head.

## Конкретное поведение

- Новый AgentRun получает secret-free snapshot актуальных main/fast/twin до первого LLM. Начатый/HITL/recovered AR использует собственный snapshot. SimRun initial snapshot — metadata; только explicit main override фиксирует INITIAL main parameters, fast/twin остаются актуальными для новых AR.
- Mutable current-main/default и provider одной роли не переключают authoritative роли другого/старого AR. Только explicit `Settings.llm_provider` и internal `ProviderChain.offline_mode` принудительно переводят все автоматические роли в mock/replay. Не выводим intent из отсутствия env credentials или списка names. Старый явный offline caller получает отдельный provenance snapshot, без придуманной истории legacy AR.
- Setup `test-llm` и выбранный benchmark profile сохраняют существующий явный diagnostic intent вне автоматического AR режима. Они используют те же binding/SDK budget/close guards; offline0HTTP не заявляется для намеренной diagnostic API проверки.
- `llm_api_keys` — единственный writable credential source: pgp_sym_encrypt(APP_SECRET), private stable UID, endpoint/scope metadata. ID/UID повторно не выделяются как новая account identity для alias/re-add того же значения. UID/cipher/plain не выдаются API. Unbound profile сохраняет явно документированный legacy env source; выбранный missing/inactive/wrong-provider/wrong-endpoint key не подменяется env.
- DELETE bound key возвращает409 до явного profile `api_key_id:null`. Отсутствие поля при PATCH старого клиента сохраняет binding. Soft deletion сохраняет identity и отзывает credential для начатых snapshots. Старый bench `extra.api_key_id` поддерживается только как явная read compatibility: нормализуется в public/API field, новые writes в extra запрещены, conflicting значения отвергаются.
- Legacy enc1 import — одна транзакция под advisory510013, с безопасным конфликтом ID/provider/plain equality. До успешного commit old encrypted row не удаляется. Scoped0013 trigger запрещает INSERT/UPDATE `settings.llm_keys`, включая старую версию приложения; DELETE конвертера разрешён. Это forward migration, не обещание совместимости старого writable приложения: rollback требует остановки app и reviewed recovery/conversion из config backup, затем согласованного source. Нельзя запускать старый writer параллельно или обходить trigger в prod.
- Повторный cutover не пере-шифровывает строки и не создаёт фиктивный config drift. Specific trigger отключается только в synthetic fixture transaction для моделирования ДО-upgrade row, с finally re-enable/savepoint/rollback.
- Bound runtime HTTP client закрывается в finally. Giga private per-loop ApiKey/OAuth-lock state сохраняет прежние in-memory usage/health между вызовами, в том числе alias identity; explicit lifespan cleanup после drain разрывает loop/Lock ссылки. Durable admission/reset history не заявляется: T-050 P2 отдельно. Existing bench observations остаются в transaction вместе с result, теперь в canonical store; quota-error fictional tokens_used=limit не персистируется как actual spending.

## Credential boundary

Публичные key projections положительные; private значения и неизвестные будущие private fields не пролезают через generic settings/export/engine DB. Invalid credential/config input errors не включают Pydantic input/ctx. Secret URL/query/fragment/extra и ambiguously shadowed binding не допускаются. Все selected roles/bound metadata проверяются до destructive baseline reset даже без body profile ID; metadata повторно проверяется внутри существующего exclusive maintenance preflight.

Giga OAuth/chat error diagnostics сохраняют kind/status/Retry-After/usage/retry behavior, но upstream body и network exception values не идут в KeyPool logs/API. Exact selected credential и Giga bearer token в model raw/parsed JSON вызывают constant bad_output до return/trace/persistence: ответ не маскируется и не подменяется. Known response usage при отказе сохраняется. Stream держит только неоднозначный literal prefix, поэтому split credential не выдаётся по кускам. Обычный trace/text не редактируется. OAuth `access_token` — ожидаемое private поле протокола, никогда не public model output; echo authkey в иных OAuth полях отклоняется. Произвольные сторонние debug handlers/opaque энкодинги не объявляются защищёнными универсально.

## Проверки source checkpoint

-146 pure tests (SDK/Giga/credential/reflection/offline/profile/bench guards),2.85s.
- PG11routing/tracing/profile tests,47.34s, все исходные model/cost/idempotency assertions сохранены. Два live-routed RecordingProvider fixtures явно задают `LLM_PROVIDER=gigachat` и очищают cache; физически остаются memory Fake без HTTP.
- PG16 API/bench tests,71.13s на промежуточном дереве. Расширенный набор дал23pass/2fail из-за cached logger в закрытый capsys fixture; fixture устранён, targeted6passed/11deselected,23.29s. Полный окончательный набор будет повторён после maintenance merge.
- Generation выполнена own checkout и исключительно `cx_profile_hotapply_revision`; ruff/format/mypy255 проходили адресно. Предыдущая база отдельно:1038unit/18skip+22PG+171front, не переносится автоматически на P1.
- No live LLM, production data, env/key registry inspection, canonical venv mutation, push/PR/main merge.

## Обязательный review перед merge

`contract-change`/`cross-layer`: DB0013 + API1.5.18, source transition/rollback, diagnostic egress boundary, selected-key authority, effective per-AR profile semantics и actual SDK budget guards. Ни rates/default budgets, ни банковские суммы/refund/HITL thresholds не менялись. Usage/balance/day/last_error не входят в baseline fingerprint; private UID/endpoint/scope/limits/deleted config входят. Номер0016 зарезервирован parent для отдельно reviewed durable operational store;0014 принадлежит T-240.


## Составной checkpoint после297a8459 (в работе)

Ordinary merge сохраняет maintenance coordinator, DB boundary/marker и API17 вместе с P1API18/0013. Selected-role metadata повторно проверяется внутри exclusive preflight после drain, до park/restore; эта проверка не decrypt/convert и не делает HTTP. Canonical new identity/endpoint/scope/RPD/deleted-config входит в opaque LLM fingerprint; usage/balance/day/last_error/timestamps не входят. Source не дублирует maintenance guard.

Точный T120 стык: signal.appended продолжает использовать child HITL guard; reply daemon запускается через start_daemon, poll проходит writer lease, continuation регистрируется spawn_writer до первого шага. Restore ждёт reply pipeline, а не получает stale task после нового epoch.

Дополнительная security boundary: raw и уже decoded modelJSON проверяются, включая Unicode escapes/codefence. Structured/quoted JSON/codefence stream держит fragment до complete, ≤64KiB UTF-8; prefix plaintext уже выдаётся, после него fallback запрещён. Limit включает fences/whitespace. При overflow/cancel/deadline iterator/HTTP response закрываются; known cumulative stream usage прикрепляется к ошибке, отсутствие usage остаётся None. Обычный unmarked plaintext не буферизуется целиком. Это конкретное изменение latency, а не обещание универсального DLP/распознавания всех кодировок.

При source audit исправлена собственная role regression: TeamEmulator сохраняет caller twin, Compliance detector — caller fast вместо случайной замены наmain. No-LLM verification/notification/manual traces получают явный no_llm_execution и не зависят от текущих keys. Completed manager role trace получает pre-call snapshot от вызывающего кода, а не текущую конфигурацию после LLM. Frozen Deps loading проверяет структуру snapshot, но не decrypt/валидирует unused credential; metadata authority обязательна перед реальным network invocation. Real approved static HITL remainder проходит после deactivation/deletion synthetic key; actual network и новый AR/preflight при этом отказывают.

Новые подтверждения:191 directed pure tests прошли до последних actor-role изменений;4 PG case (metadata-no-decrypt, fingerprint, approved static resume with inactive/deleted key) прошли16.09s. Полные проверки окончательного состава ещё не запускались; их результаты будут добавлены отдельно.

Проверка composed backend: полный `tests/unit` —1145passed/18skipped26.82s; targeted baseline/maintenance/benchmark46passed, caller-role/no-LLM17passed. Первый полный прогон обнаружил9 fixture несовместимостей: AsyncMock transaction/preflight protocol и совпадение слишком общего fake credential `synthetic` с suffix имени fake модели. Исправлены только fixtures/доступность отсутствующего baseline проверяется до открытия DB; исходные assertions preserved, reflection guard не ослаблен. PG/full composite и UI ещё не являются доказанными на этом checkpoint.

## Полный составной прогон11f152

`make lint` зелёный:195 frontend tests, ruff375files, mypy260sources, OpenAPI191/191. Production+personal build прошли, licenses550, i18n1697/fresh API types. `make test`: contracts44/161; unit1145passed/18skipped26.90s; integration291passed/2failed/2skipped1148.03s. До scenarios/compliance/frontend этот make не дошёл. Это НЕ full green.

Два подтверждённых отказа: durable process записал recover/graceful reports, но child превысил45s при завершении; первая установка упала ДО seed/assertions на FK старого `langgraph.checkpoints`→новая пустая `sim_runs`, потому что отдельная test fixture сбрасывает только public namespace. Assertions/timeouts не ослаблены; причина shutdown ещё исследуется.

## Legacy boundary baseline

Непустая неконвертированная `settings.llm_keys` блокирует snapshot/restore constant409 до marker/drain/pause/export/pg_dump/restore. Guard читает только SQL EXISTS boolean, не возвращает/читает credential values, не decrypt и не конвертирует store. Missing row, пустой список и JSON null разрешены; malformed nonempty payload отказывает. Повторная проверка fingerprint внутри согласованной maintenance boundary сохраняется для race protection.

Оператор должен явно открыть реестр API-ключей или выполнить reviewed cutover. GET `/api/settings/llm-keys` выполняет transactional/idempotent migration и удаляет legacy row только при успехе; в production также сохраняет существующее обновление metadata баланса. Поэтому эти GET не объявляются универсально read-only. Пустой JSON null нормализуется как прежним loader в пустой registry при явном cutover. После удаления legacy row fingerprint включает только canonical config; счётчики spending туда не добавляются.

Target guard+baseline/maintenance unit50passed16.19s. В новом PG case проверены HTTP409 обоих endpoints, неизменность marker bytes/mtime/phase/epoch/job, живой writer actor, RNG и sim_state; pg_dump/pause/shutdown не вызываются. После явного successful cutover sync/async fingerprint совпадают.

## Конечная composition base

Ordinary merge PR172/db4c286 сохраняет API1.5.18 со всеми T234 optional fields/relations paths, UI key bindings, DB/Compare tabs и TraceGraph. WS runs инвалидирует db и trace вместе. Public `app.openapi()` выполняется после регистрации routes/mount_frontend, без вызовов DB/LLM. Generated API types пересозданы source generator, diff отсутствует. Composed frontend220passed.

Directed metadata/profile/Trace run:98passed/1failed184.06s. Единственный отказ — synthetic GET cache probe после локального production build попадал в существующий SPA fallback и получал HTML. Probe меняет только synthetic cache; теперь POST `/api/synthetic-runtime-state`, исходные stored/loop-cleanup assertions сохранены. Exact regression1passed1.85s. Продуктовый GET routing этим не изменялся.

## Frozen727: завершённые проверки

Unit1298passed/18skipped51.44s; PostgreSQL320passed/2skipped1749.14s; scenarios41passed/1failed/2skipped197.64s. Единственный scenario09 replay fixture сохраняла global mock и не выбирала записанную Pro модель до создания SimRun; все actual model/replay assertions сохранены, correction согласована отдельно. Поэтому `make test` НЕ объявляется green. Оставшиеся targets выполнены отдельно на том же frozen source: compliance31passed95.56s, frontend220passed.

Coverage выполнен в отдельном checkout/venv/DB того же727, без общей генерации/БД:1442passed/18skipped1082.62s; изменённые executable statements2260/2516=89.83% относительно85fcbaa, generated DB/models/contracts и line0 исключены. Per-file missing lines и source SHA в `T-051-frozen-727-coverage.json`, сводка в `T-051-frozen-727-proof.json`.

Дополнительные synthetic counterexamples подтвердили SDK raw exception cause в formatted traceback и Giga exact credential в usage до int parsing. Эти данные НЕ означают, что provider boundary уже полностью защищена. Согласован отдельный followup после frozen proof: fromNone, minimumWARNING exact installed SDK loggers и безопасный pre-parse usage boundary. Приведённые числа относятся727, не будущему изменённому source.

Provider followup описан отдельно в `T-051-provider-error-boundary.md`: безопасные causes, explicit SDK minimum WARNING и nullable unknown usage вместо fabricated0. Реальная pre0013 schema297 проверена отдельной scratch DB: повторныйDDL/cutover стабильны; existingcipher/identity/observations не изменились. Прежняя canonical row с endpointNULL остаётся unknown, не получает угаданный destination: для explicit binding оператор должен зарегистрировать тот же credential с известным endpoint (private UID повторно используется). Это migration limitation, не молчаливый env fallback.
