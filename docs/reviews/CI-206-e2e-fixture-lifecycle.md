# CI206/207: изоляция native preparation и точные UI snapshots

Изменены только четыре файла test infrastructure. Runtime application/API/DDL/денежные/HITL правила не меняются. База — immutable revision-integration `3e9e592c76fab404ab02cbd727daa07a0b7f00db`; последующая root T092 composition в этот локальный proof не входит и требует общего exact-head CI.

## Подтверждённые RED и причины

- CI206:13 failures/139passed; Map beforeAll успел205/301 AR за60s (active4,failed0). Незавершённый backlog продолжал работать в общей DB после hook failure. Следующий Jury POST ожидает настоящий graph/comparison; timeout30s закрыл per-test request context, finally потерял UI restore и скрыл первоначальную ошибку. Overview source money202.88 изменился в UI205.17→387.42→410.34 вслед за ещё работающими actors. Smoke/Themes затем наследовали v2 settings. Это не финансовый tolerance/flake.
- Исходный native host Map setup без изменения source:4/4green47.3s, все301 AR завершены/active0/failed0. Safe aggregate samples показывают progression141→301 без failed. CI205/60 даёт ожидаемый порядок≈88s для301; это массовая fixture preparation, не product API или single-signal deadline.
- Actual image attempt1 после изоляции:147passed/4Shell canonicalF/4Map dependency notrun4.7min. Jury/Overview/Smoke/Themes прошли. Shell дошёл до ранее неисполнявшейся проверки help modal `/map_mode=zones$/`, забывавшей canonical `run_id=current`.
- Attempt2 после полного canonical fix:140passed/11failed/4Map notrun7.2min. Shell дошёл до ещё одной скрытой зависимости: требовал priority incident в current live run, где настоящих incidents0. UI правильно показывал «Пока тихо…». Timeout снова объяснил downstream settings cascade. Непустые приоритеты раньше случайно обеспечивал Map scenario, который теперь честно изолирован.

## Исправление

Map cases вынесены в последний serial `scenarios` project, зависимый от `settings`. Они не дублируются в settings:58read-only+97settings →58+93+4scenarios, ровно те же155 case identifiers/25files. До read-only Map фазы конечный setup120s/hook150s требует прежние301signals/301AR/active0/missing0/duplicate0/foreign0/failed0; duration сохраняется в native preparation attachment. Обычный UI testcase30s и product timing guards не изменены.

Jury и Shell восстанавливают точный прежний namespace одним `/api/settings/import` через независимый APIRequestContext с timeout10s. Он переживает disposal per-test request; cleanup context закрывается своим finally, в insecure Jury также переживает ошибку browser.close. Native probe намеренно закрыл per-test request: exact old UI восстановлен,1/1passed408ms.

Shell hotkeys5/6 и защита help modal проверяют полный canonical URL вместе с current scope. PriorityStrip сверяется с тем HTTP response, который использовал UI после последней navigation:200, current/numeric current, точный ACTIVE status set, limit3,≤3items. При наличии items каждый selector показывает настоящий publicID и exact incident href; в пустом случае требуются0links/0buttons и точный localized empty label. Нет fake incidents, unconditional skip или предположения по другому API snapshot. Отдельный native CSI target4/4green:24viewport samples, в каждом3 actual priority IDs; полный image использует настоящую empty live ветку.

## Финальный функциональный результат

**155/155passed5.4min**, fresh actual Docker Compose `cx-ci-f3f60993d079`, exit0, retries0; Map4 реально выполнены последними, все301 drain assertions green. Header/Jury/Overview/Smoke/Themes/cabinet/report/CSI/trace и существующие mock UI cases остаются в штатном наборе. Это не утверждение, что каждый из155 случаев использует настоящий business API: прежние локальные browser mocks сохранены.

Image proof source-qualified: обычный cold Dockerfile build с `--network=none` остановился на отсутствующем apt cache (exit100); это не successful full Docker build. Для functional proof собран offline source-overlay над существующим image с идентичными source/container uv.lock+pyproject SHA; целиком заменены backend/contracts/scripts и обе уже проверенные production assets3e9. Actual candidate `/data` bind:148tracked synthetic files SHA identical source. В base image отличался только неиспользуемый README модели, перекрытый exact source bind. Внешние LLM/TG/STT/media не запускались, APP_ENVdev/Mock actors настоящие; private disposable resources удалены штатным helper.

Логи RED/green сохранены отдельно `/tmp/ci206-full-actual-image{,-final,-attempt3}.log`; RED artifacts `/tmp/ci206-image-attempt1/2`, final artifacts `/tmp/ci206-image-attempt3`. Перезаписанные штатными e2e tracked PNG сохранены в этих архивах и возвращены к исходному HEAD, не смешаны с infra patch. Machine evidence: `CI-206-e2e-proof.json`. Генератор карточек дважды идемпотентен, diffcheck/list-preservation green; full frontend/backend здесь не повторялся, т.к. application source byte-identical ранее проверенному3e9. Общий CI root composition с T092 остаётся обязательным.

Дополнительный final-source native Map JSON collector:4/4passed46.5s, setup_duration_ms=38312, четыре идентичных receipts301/301 и все remaining counters0. Выполнялся параллельно A2 backup/restore на другой DB; это functional evidence с конечным setup budget, **не p95/native performance claim**.
