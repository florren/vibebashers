# T-051 P1: configuration → execution

## Статус и состав

Код P1 готов к review, карточка остаётся `in_progress` до exact-head CI и обязательного human review. Состав: SDK/main, T-041 maintenance297a8459, API1.5.18/DB0013, Setup UIa631386, main8b225d5, согласованный schema9/новая кассета bf8516c и actual main e839d839 с causal T108 fixture962. История Git сохранена ordinary merge; push/PR/main merge выполняет интегратор.

Frozen runtime43af7af прошёл все компоненты проверки, кроме одного некаузального T108 fixture case. Его полный `make test` НЕ green: unit1484/18skip; integration342pass/1fail/2skip. На том же source отдельно завершены scenarios43/2skip, compliance31 и frontend220. После mainmerge и исправления duplicate JSON dictionaries backend/app, frontend и API contract побайтово совпадают43; меняются helper/fixture, canonical0013 comment и review docs. Полный повтор локального suite ради test-only fix не подменяется утверждением о green make: обязательный GitHub CI должен проверить финальный head.

Машинные доказательства: [frozen43 proof](T-051-frozen-43-proof.json), [coverage](T-051-final-coverage.json), [actual legacy upgrade](T-051-legacy-upgrade-proof.json). Postmerge027fd27:30 affected PostgreSQL cases прошли133.96s, включая исправленный T108, binding/restore/static HITL и step atomicity; make lint220/Ruff398/mypy268/drift192 green.

## Последний startup checkpoint

После7f96646 root Fake review выявил automatic GET /models в explicit mock startup. Sourcef05b3b0 закрывает warmup/sync для explicit Settings mock/replay и chain.offline_mode, сохраняя локальную replay role metadata и intentional diagnostic APIs.45targetpassed, scoped16/17=94.12%, make lint220/Ruff398/mypy268/drift192 green. [Startup report](T-051-startup-offline.md). Frozen43 proof и90.55% whole-packet coverage выше относятся к прежнему source; их нельзя объявлять полным green нового head. Final exact CI обязателен.

## Профили и выполнение

Новый AgentRun получает secret-free snapshot актуальных main/fast/twin до первого LLM. Начатый/HITL/recovered AR использует свой snapshot. SimRun initial snapshot остаётся воспроизводимой metadata; explicit SimRun main ID фиксирует INITIAL main parameters, а не позднее изменённую строку с тем же ID. Только main переопределён; fast/twin актуальны для следующих AR. Legacy AR не получает выдуманную историю.

Mutable current-main/default и provider одной роли не переключают другие/старые authoritative роли. Принудительный offline задаётся только explicit Settings.llm_provider mock/replay или internal ProviderChain.offline_mode; отсутствие env key либо список names сами не означают permission добавить live provider. TeamEmulator сохраняет caller twin, Compliance — fast. No-LLM trace имеет no_llm_execution и не изображает LLM/profile/model. Frozen Deps не decrypt и не проверяет unused credential: одобренный статический HITL remainder работает после отзыва ключа. Перед фактическим network invocation binding проверяется строго; fallback на env запрещён.

Setup test-llm и выбранный benchmark profile сохраняют явный diagnostic intent вне автоматического AR offline режима. Они используют те же binding/endpoint/SDK budget/close guards; automatic offline0HTTP не заявляется для намеренной диагностической API проверки. Все проверки P1 использовали Fake/mock без реального egress.

## Единый credential source и миграция

llm_api_keys — единственный writable credential source: pgp_sym_encrypt(APP_SECRET), private stable UID, endpoint/scope metadata. Alias/re-add того же значения сохраняет логическую identity. UID/cipher/plain не выдаются public API. Unbound profile сохраняет документированный legacy env source; explicit missing/inactive/wrong-provider/wrong-endpoint key не подменяется env. DELETE bound key возвращает409 до явного unbind; PATCH omission сохраняет binding, null снимает. Soft deletion сохраняет private identity. Старый bench extra.api_key_id поддержан только как явная read compatibility; новые writes в extra и conflicting values запрещены.

enc1 cutover выполняется одной транзакцией под advisory510013: конфликт ID/provider/plain equality отменяет весь import; legacy encrypted row удаляется только после успеха. Повторный cutover не re-encrypt и не создаёт config drift. Scoped0013 trigger блокирует INSERT/UPDATE settings.llm_keys, включая старое приложение; DELETE конвертера разрешён. Synthetic fixture отключает только этот trigger внутри transaction с guaranteed re-enable/savepoint/rollback.

Это forward-only migration. Старый writable app несовместим с новой границей; downgrade не удаляет ciphertext или blocker. Recovery требует остановки app и reviewed conversion из config backup, затем согласованной версии source. Нельзя обходить trigger в production или запускать два writers. Прежний canonical endpointNULL остаётся unknown: оператор регистрирует тот же credential с известным endpoint и явно меняет binding; destination не угадывается, private UID сохраняется.

Actual main8b schema0010 проверена в новой scratch DB: sequential0011/12/13 и их повтор сохраняют старые SimRun, AR outcomes, ciphertext/usage/identity; legacy snapshots остаютсяNULL. Checkpoint namespace создан, old writer23514 и bound DELETE FK restriction проверены, enc1 import повторяемый, public output не содержит private values. Это синтетические данные, не production upgrade.

## Baseline и runtime ownership

Непустая unconverted settings.llm_keys блокирует snapshot/restore constant409 до marker/drain/pause/export/pg_dump/restore. Guard читает только EXISTS boolean, не decrypt/convert и не делает HTTP. Missing row, [] и JSON null разрешены. Explicit registry GET/list выполняет transactional cutover; в production также сохраняет прежний refresh balance metadata, поэтому эти GET не объявляются универсально read-only.

ALL selected roles/bound metadata проверяются до destructive reset даже при body profileNone и повторно внутри существующего exclusive maintenance preflight. Source не дублирует maintenance guard. UID/endpoint/scope/limits/deleted config входят в opaque LLM fingerprint; usage/balance/day/errors/timestamps исключены. SimRun-start snapshot остаётся metadata.

Canonical Alembic0013 comment синхронизирован с уже существующим backend Forward-only mirror. Полная regeneration выполнена в own checkout/DB. ALL baseline_contract fingerprint input bytes остались идентичными43: canonical source comment исправлен, executable SQL/DDL и backend mirror не изменены. Новый baseline из-за этого comment-only sync сам по себе не требуется; сам upgrade0013 меняет contract и требует совместимого нового baseline.

Bound HTTP client закрывается finally. Giga per-loop ApiKey/OAuth-lock state сохраняет in-memory usage/health через alias clients, explicit lifespan cleanup после drain разрывает loop/Lock ссылки. Durable quota/reset history не заявляется: T-050 P2/0016 отдельно. Canonical observations сохраняются с benchmark result; quota errors не изображаются как actual spending.

## Credential/error boundary

Public projections положительные, включая generic settings/export/engine DB/audit; unknown private fields не проходят. Credential/config422 не возвращает input/ctx. URL userinfo/query/fragment, secret-bearing extra и shadowed binding отвергаются.

Exact selected credential/bearer token в model raw/decoded JSON отклоняется до trace/persistence. Structured/quoted JSON/codefence stream буферизуется до complete, максимум64KiB UTF-8; ordinary plaintext сохраняет rolling-prefix latency. Overflow/cancel/deadline закрывают iterator/client; после уже выданного plaintext prefix fallback запрещён. Ответ не подменяется sanitized JSON. Arbitrary encoded exfiltration/general DLP не заявляется.

Отдельный [provider boundary report](T-051-provider-error-boundary.md) фиксирует constant upstream errors/fromNone, minimumWARNING exact SDK loggers после OPENAI_LOG setup и pre-parse usage guards. Known response usage сохраняется; начавшийся wire без validated usage остаётсяNone. Pick/admission request_count0 доказывает0HTTP и сохраняет legitimate known0. Internal attempt counter не удваивает known usage. Цены, numeric budgets и банковские refund/HITL thresholds не менялись.

## Сопутствующие подтверждённые дефекты

Dedicated pause/stop устраняет Python-lock/SQL-row-lock inversion: stop loop до lock, один Python lock до status writes/commit, publish после release, rollback при ошибке/отмене. Original OS-process45s/assertions сохранены. Failed step восстанавливает clock/RNG/stats и committed World cache, сохраняет прежние volatile pending и отбрасывает новые uncommitted pending/faults/team/SLA. Это сохранение существующей queue, не durable timers. [Atomicity report](T-051-step-atomicity.md).

## Проверки и обязательный review

Frozen43 make lint green: frontend220, Ruff398files, mypy268sources, OpenAPI192/192. Contracts45schemas/162paths. Coverage2903/3206 изменённых executable statements=90.55% относительно dependency checkpoint85fcbaa: все изменённые app files измерены fresh43 trace; reuse727 допустим только при exactgitblob equality, zero-hit файлы имеют0. Измерительный suite1580pass/19skip; generated files/line0 исключены. Это явно composite provenance, не притворный single-source fullrun.

T108 sole failure: incident_signals.fetchone()=None в старой fixture, test_engine_db_api.py:41. Main962 задаёт failed DEP operations внутри own old/current runs, более новый unrelated QR decoy, simulation clock и mass-клиента без прошлого tech_fault14d. Исходные DB/API assertions сохранены и усилены causal/run ownership. После composition30 affected PG cases и make lint прошли. Финальные gates: contracts45/162, i18n1804/fresh TS, licenses550, production+personal build green; final exact-head CI обязателен.

Исторические727 proof/coverage сохранены отдельно и не объявляются доказательством нового source. UI verification:189 Vitest на UIcheckpoint,4 production fakeAPI screenshots ru/en×light/dark в docs/screenshots/T-051; composed frontend220. [UI report](T-051-profile-keys-ui.md).

Перед merge нужны contract-change/cross-layer human review API1.5.18/DB0013, forward recovery, selected-key authority, per-AR semantics, diagnostic egress boundary, nullable usage и SDK logging policy. В рамках P1 production/env/private-registry inspection, canonical venv mutation, real LLM/TG/email calls или remote writes не выполнялись. Live validation именно P1 bound-key hot apply не проводилась. P2/0016, T240/0014, T121/0015 и T161/0017 не входят в этот implementation packet.
