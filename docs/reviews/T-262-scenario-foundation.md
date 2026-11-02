# T262 — native Mock foundation, не полная приёмка

Ветка `codex/T-262-scenarios`, база CSI API1.5.28 `d9af732` + обычная композиция T244 `8f4e82c`. API28 сохранён; нового HTTP endpoint, DDL, зависимости или версии API нет. Исходный T247 corpus не меняется. Рабочий стенд/production не использовались.

## Проверенные причины пробелов

- Catalog numbers14/15 уже заняты прежними входами. Они и entries1..33 сохраняются; новые IDs `cabinet_red_words_report`/`csi_and_branches` получают34/35 и private metadata `tz_number:14/15`.
- Native legal input с «суд»/«налоговую» правильно заканчивается `awaiting_human`, legal_regulatory и pending human decision. До human continuation нет executed product route. Отдельный ordinary deposit input проверяет настоящий facade `route_to_product_team` → `route_to_department`, team_deposits. Автопринятия HITL нет.
- Mock ранее не заполнял optional `product_line`. Однозначный mapping берётся из существующего canonical product_lines loader; ambiguous credit/unknown не угадываются. Provider/usage остаются Mock, а не replay/live.
- Normal/instant producer писал classification JSON, оставляя physical `signals.product_line_code=NULL`. Кабинет/отчёт берут physical field. Общий `classification_store.save` сохраняет FK-known validated line в том же caller TX, не меняя schema/prompt/routing/HITL/денег.
- Editorial baseline projection сохраняется только с exact annotation, native accepted same-run seed ingest, одинаковым seed_instance и per-run receipt (seed/reference_anchor/offset/hash). CSI требует actual csi_response. Одной raw meta или kind=baseline недостаточно. Модельный JSON/step остаётся честным отдельно от editorial physical source. Native baseline unknown очищает прежнее runtime значение.

## Подготовка CSI

Только эти два новых named scenarios используют уже существующий paused-start путь. Preflight проверяет effective capture всех main/fast/twin после P1 Settings Mock/offline override, а не один raw profile label. Live/replay пока unsupported: профиль/настройки автоматически не меняются.

Существующий scoped generator даёт300 строк,10 cohorts и2400 sampled visits. XLSX действительно строится и читается `parse_xlsx`, затем `import_rows` вызывает normalizer; `install_scoped_sample` регистрирует реальную принадлежность и visits. События `signal.received` не подавляются. APP_ENV=test не запускает listeners; это не обещание нулевого числа model calls на обычном работающем Mock runtime.

Дополнительная301-я строка — явно учебная жалоба в существующее native closed ВСП в90-day window. Для неё не создаются wait/service/employee/visits; она uncohorted, denominator неизвестен. Дата/статус отделения, consent и clock не исправляются. Аналитика читает registered scoped300/2400; global legacy denominator не используется. Native received dates и cohort response window показываются существующим API отдельно.

В `sim_runs.settings_snapshot.t262_inputs` сохраняются version1, два свободных300-ID блока, seed, native clock, closed branch code, XLSX SHA256, cohort SHA256, prepared marker. Второй блок занят целиком, хотя используется один ID. Под existing cohort advisory lock учитываются все csi_responses, CSI ingest IDs (включая rejected) и reservation других headers. SimState/run locks следуют native lock order. Reservation commit предшествует import TX; ошибка не освобождает IDs для чужого run. Весь import/registration/prepared marker атомарны. Exact retry/restart реконструирует тот же XLSX; ZIP timestamps собственного файла канонизированы, properties закреплены native clock. Hash/source/version mismatch — явный отказ, без overwrite/rekey.

Явный retry после остановленного failed preparation: `python scripts/scenario_prepare.py --run-id <свой-current-paused-run>`, с тем же операторским окружением и effective Mock. Команда не создаёт новый run и не сбрасывает baseline. Повторный обычный POST создаёт новый run по прежней семантике сценариев и получает новый свободный allocation.

## Честная приёмка и ограничения

Native backend checks публикуются отдельным `native_mock_foundation`. Неизвестный expected key получает `ok:null`, `not_verified` и не считается успехом. Обязательные pending UI/replay checks тоже `ok:null`: общий `passed=False`, пока они не проверены. Совместимость старых сценариев с legacy NOT_YET не меняется.

CLI дополнительно читает существующие metrics preview (canonical deposit961), настоящий XLSX report, CSI probabilities/coverage и closed branch detail. Эти чтения не создают AR, денег или фиктивной классификации. Manager-scoped JSON/XLSX обязан содержать именно native refs входов, а не просто любую baseline строку.

Не закрыты: UI T242/T249/T250, Playwright обеих тем/языков, полная human continuation legal input и replay. Исходная стрелка ТЗ§18 «HITL → route» требует явного ручного решения, а не runtime bypass. Это конкретное уточнение для final review, не молчаливое снижение acceptance. T238 benchmark/accuracy на основном провайдере этим prerequisite не закрывается.

## План настоящего replay

После композиции UI и полного Mock proof зафиксировать synthetic bank/inputs, plan hashes, role snapshots, prompt/schema versions и current request hashes. Составить bounded recording plan с числом model calls/стоимостью и получить отдельное разрешение реального provider recording. Запись проходит штатным recorder, сохраняет raw usage/response, не rekey старых кассет. Затем replay-only повтор из того же frozen input и negative stale/current-hash проверки. Ни кассеты, ни LLM outputs/AR сейчас не изготавливались вручную.

## Recovery / rollback

До публикации достаточно вернуть source к предыдущему checkpoint. Новый код не меняет DDL/старые IDs. После reservation/import не удалять чужие CSI/ingest/headers и не переназначать ID. При source hash mismatch восстановить именно прежний source/lock и проверить manifest либо создать отдельный новый run; не подменять SHA. Failed import TX откатывается, прежние inputs/reservation сохраняются. Закрытое ВСП вне допустимого окна или несовместимый directory требуют подходящего отдельного snapshot/run, без автоматического reset.

## Final focused verification (2026-11-03)

- 110 pure targeted tests — passed, 1.96s: Mock mapping, manifest/XLSX, CLI и прежние normalization/product-line checks.
- На final runtime source: coverage run25 tests (9 unit +16 actual PG) — passed,148.85s. `classification_store`7/7,100%; `scenario_acceptance`168/182,92%; вместе175/189,92.59%. Это line coverage, не benchmark/performance proof. [Агрегаты и SHA256 runtime files](T-262-foundation-proof.json).
- Native generic-import/preparation race сначала RED `DeadlockDetected`10.56s, затем тот же test GREEN9.82s после `FOR NO KEY UPDATE` вместо `FOR UPDATE` header. Current/paused checks и SimState pin сохранены; обычный FK KEY SHARE importer больше не образует цикл с advisory lock.
- `make lint contracts-check licenses-check` — exit0: frontend429 tests/61 files, backend Ruff520/Mypy316, bot Ruff12/Mypy5; drift195 operations без missing/extra;47 schemas/165 paths; licenses550+36. После lock fix backend lint/typecheck повторён.
- Actual Alembic check на своей DB: `No new upgrade operations detected.`; source schema/migrations не менялись.
- Полный backend suite/4-shard union пока **не запускался**: root согласует ресурсное окно после review focused checkpoint. Нельзя выдавать эти targeted результаты за full green. Рабочие/production БД не использовались; real LLM, Telegram/email и runtime human accept не выполнялись.
