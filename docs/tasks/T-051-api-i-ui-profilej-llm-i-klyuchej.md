# T-051 — API и UI профилей LLM и ключей

| Поле | Значение |
|---|---|
| Эпик | E4 LLM-слой |
| Субагент | `SA-LLM` (LLM-слой) |
| Оценка | S (≤ 0,5 дня) |
| Волна | 2 |
| Слой | `L1` Базис (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `in_progress` |

## Цель
Управление провайдерами из настроек: роли main/fast/twin, активность, ключи, лимиты.

## Разделы ТЗ (docs/TZ.md)
§12.2 экран 5, §5.2

## Контракты
- `api/openapi.yaml: settings/llm-profiles, settings/llm-keys, setup/test-llm`

## Зависимости
- Зависит от: [T-050](T-050-rate-limiter-byudzhety-fallback-i-maskirovanie-s.md), [T-010](T-010-ui-mastera-nastrojki-9-shagov-i-ekran-nastrojki.md)
- Блокирует: —

## Что сделать
1. CRUD профилей и ключей по контракту (ключ только writeOnly, шифрование pgp_sym_encrypt APP_SECRET).
2. UI-вкладка: таблица профилей с ролями, кнопка «Проверить», индикаторы остатка токенов/лимитов/баланса, предупреждения.

## Критерии приёмки
- [x] Смена main-профиля применяется к следующему запуску агента без рестарта.
- [x] Ключ не возвращается ни одним API.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/integration/test_llm_settings_api.py
```

## Отчёт субагента
P1 код готов к review в codex/T-051-runtime-profiles, API1.5.18/DB0013. Новый AR hotapplies текущие main/fast/twin; начатый/HITL/recovered AR pinned собственным secret-free snapshot. Explicit SimRun main ID фиксирует initial main parameters; остальные роли актуальны для нового AR. Canonical PGP registry, transactional enc1 cutover, private stable UID/endpoint binding, DELETE409 до явного unbind, positive public projections и validation/error/stream credential boundary реализованы. Forced mock/replay не даёт HTTP автоматическим ролям; intentional Setup/bench diagnostics сохраняют прежний intent. Реальных вызовов P1 не было.

Setup UIa631386 объединён: selected ID/null Save/Check, endpoint/scope/key metadata, writeOnly field cleanup, explicit server validation без guessedURL.4 production fakeAPI screenshots ru/en×light/dark и189 Vitest UIcheckpoint; composed frontend220. Source сохраняет maintenance297, финансовые guards main и quota stream policy8b; main e839/causal T108962 объединён ordinary merge.

Frozen43: contracts45/162, unit1484pass/18skip, integration342pass/1fail/2skip; остальные targets отдельно на том же source: scenarios43pass/2skip, compliance31, frontend220. Единственный F — некаузальная T108 fixture без incident; исходные assertions сохранены в current-main fix. Поэтому local make test НЕ объявляется green. make lint green220/Ruff398/mypy268/drift192. Coverage2903/3206=90.55% с явной exact-blob/fresh43 provenance; suite1580pass/19skip. Actual main0010→0011/12/13 synthetic upgrade/repeat/cutover сохранность и failclosed rollback boundary проверены. После mainmerge backend/app, frontend, API и baseline fingerprint input bytes идентичны43; canonical0013 comment source синхронизирован полной regeneration.

Postmerge027fd27:30 affected PG passed133.96s (исправленный T108, runtime profiles, step atomicity), make lint220/Ruff398/mypy268/drift192 green. Финальные contracts45/162, i18n1804/fresh TS, licenses550, production+personal build green. До done: exact final-head GitHub CI и обязательное human review DB/API/credential/budget/cross-layer diff. Карточка остаётся in_progress. Persistent quotas — отдельно T050 P2/0016; numeric rates/customer money/HITL policies не менялись. Проверки offline/Fake; live validation именно bound-key hot apply отсутствует. Подробности и machine proofs: docs/reviews/T-051-runtime-profiles.md, T-051-frozen-43-proof.json, T-051-final-coverage.json, T-051-legacy-upgrade-proof.json; provider/atomicity/UI reports доступны по ссылкам в основном отчёте.


Последний bounded followupf05b3b0: explicit mock/replay startup больше не делает Giga warmup/OpenRouter catalog sync, даже при сохранённом physical live provider. Local replay config refresh и intentional diagnostic APIs сохранены.45targetpassed, startup scopedcoverage94.12%, make lint220/Ruff398/mypy268/drift192green; root counterexample Fake-only, никаких новых real calls. Frozen43 aggregate/90.55% coverage не объявляются полным прогоном нового source. Report: docs/reviews/T-051-startup-offline.md; final exact-head CI/review остаются обязательными.
