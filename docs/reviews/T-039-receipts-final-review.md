# T039 B: конкретная граница receipts/runtime review

Пользователь подтвердил вариант B для реализации 02.11.2026. Это отдельный packet после T161/T037 и actual0018, не изменение их уже согласованной policy. Финальный concrete DDL/consumer review остаётся обязательным; completion всей T039 и публичный API этим документом не утверждаются.

## Контракт и совместимость

Actual0019 после0018 добавляет только nullable behavior_receipts.details JSONB, без default/backfill/новой таблицы. Canonical SQL, mirror, Alembic wrapper и generated model подготовлены storage checkpoint27a8956. Миграции0017/0018 не переписываются. Legacy NULL остаётся unknown; SQL shape validator принимает только bounded version1/13keys/native kinds/aware times/positive integer-not-bool IDs и2048bytes. Shape check сам по себе не подтверждает lineage.

Новый writer вызывается только из существующих `_resolution`/`_agent_intent` после прежних guards. Блокируются native pending work своего run/client/episode; reason receipt и work.status записываются в одной caller tick TX. Проверяются persisted evidence и для already_complained — canonical signal/intent. Сбой после первого receipt/status откатывает оба, closure и RNG. Restart/retry/два owner не дублируют reason или credit. Потерянную legacy provenance автоматически не восстанавливаем.

Времена различаются: cancellation_sim/consumed_sim — прежнее logical время отмены; cancellation_observed_sim — horizon текущего owner advance; resolution_sim — последняя обязательная native resolution всех причин, не horizon и не время уведомления. Связанная фактическая жалоба сохраняет signal.received_sim, даже если classifier observed позднее. Unknown classifier не является neutral. Проактивный service origin, baseline и foreign client/run не становятся customer complaint.

## Modelled summary

Внутренний `app.sim.behavior.prevention.summarize(conn, run_id=...)` возвращает typed PreventionSummary. Public endpoint/поля не добавлены, OpenAPI остаётся1.5.22; API27 не расходуется. Consumer существующего T039 report компонуется отдельно с владельцем.

Modelled credit получает только ранее запланированный primary complaint, отменённый verified resolution строго раньше due и без первой связанной canonical complaint. Already-complained/repeat/patience, равенство due, Sent/care, unknown resolution/completeness/legacy NULL не кредитуются. При неполной provenance общий modelled_prevented_by_resolution=NULL; recorded_eligible_count — только подтверждённая часть, не подмена неизвестного total нулём. Отдельно видны unknown cancellations, recorded receipts и pending primary timers; эти технические счётчики не объявляются взаимоисключающим разбиением.

Reader перепроверяет связанные native inputs: ранее невидимая concurrent TX с prior received signal не оставляет вечный credit. Immutable receipt не переписывается; summary отражает доступные факты чтения и может консервативно стать unknown/не дать credit после появления таких фактов. Никакого attribution уведомлению, prevented_loss_rub или нового отображения churn_risk нет.

## Неизменённая policy

Нет нового RNG draw, вероятности p_complain, delay/cadence/deadlines, care weights, retained threshold, dCLTV, платежей или HITL. Существующие условия cancellation и количество work не меняются. Canonical classifier validation выделена в helper, прежний complaint predicate сохранён; generic import gold не становится фактом классификации.

## Доказательства

- Storage: actual0018→0019 сохраняет PK/row hash и SQL NULL legacy receipt; повтор DDL дважды идемпотентен. [Storage proof](T-039-receipts-storage-proof.json), исходный checkpoint27a8956; actual19→20 отдельно проверен root на собственной CSI БД.
- Runtime/codec/storage + исходные canonical-signal/owner-resolution regressions под coverage: **76 passed,142.69s** (`/tmp/t039-receipts-runtime-coverage-tests.log`). Включены native last-cause time, unknown/neutral/actual negative, partial-write rollback, unchanged RNG, two-owner/reconnect/retry, foreign-client evidence, forged rich lineage и late committed prior input из другой connection.
- Changed executable runtime coverage **127/136=93.38%**: cancellation64/72, prevention49/50, изменённые owner5/5 и signals9/9; codec отдельно86/87. Это line coverage, не branch coverage. [Source-qualified proof](T-039-receipts-runtime-proof.json).
- Полный unit suite того же runtime source: **1900 passed,18 skipped,57.00s** (`/tmp/t039-receipts-full-unit.log`).
- Ruff/formatter и mypy четырёх runtime файлов — green на проверенном source. Authoritative make sync-contracts:110ORM, без tracked generator delta. make lint green: backend489Ruff/307mypy, bot12Ruff/5mypy, frontend366Vitest/47files/typecheck; inherited DemoMenu1warning,0errors. Contracts47schemas/163paths/drift193=193, licenses550+36 green. Остальные regression фиксируются отдельно после завершения; targeted76 не объявляется полным suite.

Данные — собственная synthetic scratch PG16 cx_prevention_receipts_revision. Production, реальные LLM/Telegram/email не использовались. Coverage взят из уже подготовленного изолированного scratch tool без установки dependencies в project/shared venv; pure Python tracer (C extension недоступна), успешный data file и source hashes сохранены.

## Rollback и операционная граница

DDL0019 требует штатного maintenance/migration окна: ALTER/CHECK может ждать writers. Меняется DB contract fingerprint; старому baseline не подставляется выдуманная metadata. Downgrade сохраняет audit column/историю, физический DROP не выполняется. При rollback приложения keep0019 migration/contract knowledge, остановить actors штатно; старый app может писать NULL, новый reader обязан сохранить unknown. Receipt/status не разрывать и не backfill вручную для получения красивого счётчика. Рабочие БД не изменялись.
