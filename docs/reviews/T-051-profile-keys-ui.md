# T-051 — профиль → сохранённый ключ: UI checkpoint

Ветка `codex/T-051-profile-keys-ui`, база backend source83516b7. Только frontend/UI и документация; backend, contracts, migrations и рабочая `t051-runtime-profiles` не менялись. Это focused UI-коммит для интеграции в P1, не отдельное утверждение готовности всего T-051.

## Поведение

- В существующем StepLLM появился selector сохранённых API-ключей для профиля и компактный registry. Профиль сохраняет только api_key_id; GET key-list используется в типах generatedAPI1.5.18. Удалено лишнее ручное сужение nullable key_hint, create body выведен из generated requestBody (включая endpoint/scope/limits).
- Bound inactive/missing/wrong-provider/wrong-known-endpoint/scope остаётся выбранным с явной ошибкой, Save/Check заблокированы до исправления. Refresh не переключает пользователя на env. Опции — активные ключи соответствующего provider; несовместимые endpoints disabled.
- Обычный PATCH не содержит api_key_id и сохраняет серверный binding; ID/null отправляются только после явного изменения selector. После сохранения следующий unchanged PATCH опять omits поле. Activate/deactivate тоже omits binding и сохраняет прежний URL, не захватывая несохранённые drafts.
- Check использует выбранные provider/model/base_url/api_key_id без plaintext key. Unbound по явному выбору omits поле diagnostic request, как требует generated API. Ни Check, ни внешний вызов не запускаются автоматически при загрузке/Save/refresh.
- Effective Giga endpoint при base_url=null не выдаётся имеющимся public API. UI не угадывает default, не подставляет endpoint ключа в профиль, не блокирует весь экран: показывает server-validation hint. Прежняя hardcoded подстановка Giga URL при создании также убрана; пустой URL наследует настройку сервера, явный пользовательский URL сохраняется. API Save/Check authoritative. Известные explicit URL/OpenRouter default и configured Giga scope проверяются локально; env producer не расширялся.
- Key CRUD ровно по API18: GET/POST/DELETE, DELETE409 явно сообщает о необходимости unbind. PATCH ключей в API отсутствует и не придуман; active/status ключа read-only, edit/active профиля сохранены. Endpoint/scope optional при создании, пустые значения omitted и разрешаются сервером. Лимиты/баланс выводятся только из public counters, остаток токенов — max(0,limit-used) при обоих известных значениях; отсутствие данных — «—».
- Password writeOnly, без prepopulate/persistence. После success очищается; mutation observer reset+gcTime0 удаляют secret variables из mutation cache. В интерфейсе — только label/masked hint. Create/delete/check ошибки отображаются безопасными локализованными сообщениями; сырой provider error/opaque quota JSON не выводятся. Результат Check инвалидирует public registry, чтобы обновить расход.
- Исправлена подсказка источников: registry PGP отделён от server/env. Неактивные строки больше не получают opacity50 для текста/ошибок; выделяются поверхностью, сохраняющей контраст. Новых страниц, моделей по умолчанию, тарифов/лимитов и политик нет.

## Проверки

- Полный frontend Vitest: **189 passed**,7,32с; в том числе **19 целевых** (8 binding/helper,10 UI,1 прежний URL regression). Tests покрывают omission/null/ID, повторный Save, provider-switch без auto-unbind, inactive/missing/wrong endpoint/provider, unknown Giga default, create DTO endpoint/scope, password/reset/cache, safe errors/DELETE409.
- Production Playwright: **4/4 passed**,4,6с, ru/en ×light/dark. Fake/local API transport: create→bind новогоID→Check, explicit null/omission, inactive/missing guards, no plaintext в DOM, password очищен, DELETE409, global overflow≤2px, page errors/external requests0.
- TypeScript typecheck/ESLint green (существующий DemoMenu fast-refresh warning). Оба production build green (существующий chunk-size warning). Generated API TS идемпотентен, contracts/type/i18n/tasks проверки отдельно; backend full/lint/coverage выполняет producer после maintenance composition.
- Снимки реально отслеживаются Git: `docs/screenshots/T-051/`,4PNG+README. Логи `/tmp/vibebashers-t051-ui-{verified-unit,production-proof,verified-build,type-final-tip,verified-lint}.log`. i18n1695 keys; contracts44schemas/161paths; TS/tasks205 generation idempotent.

## Ограничения и интеграция

Нет реальных LLM/email/TG вызовов, ключей пользователя/DB mutations. UI проверялся на source83516b7 и fake transport; итоговая совместимость с maintenance/runtime checkpoints и полный PR CI остаются gates родителя. Human review API1.5.18/0013/credential migration остаётся по producer reviewdoc. Статус T-051 `in_progress`, backend/AR hot-apply/PGP/real-call DoD здесь не объявлены завершёнными.
