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
- [ ] Смена main-профиля применяется к следующему запуску агента без рестарта.
- [ ] Ключ не возвращается ни одним API.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/integration/test_llm_settings_api.py
```

## Отчёт субагента
P1, ветка `codex/T-051-runtime-profiles`: backend source checkpoint после объединённой SDK/T-041 базы85fcbaa. Миграция0013, OpenAPI1.5.18: canonical PGP key registry, explicit endpoint/provider binding, private credential UID, per-AR snapshot/hot apply, key-delete409 до явного unbind. Непрозрачный enc1 cutover transactional/idempotent; old-store writes запрещены scoped DB trigger. Публичные projections/validation errors не возвращают key/cipher/privateUID. Provider error bodies безопасны до KeyPool logging; exact credential в успешном model output отклоняется, включая split stream. Known usage сохраняется, response не подменяется.

На source checkpoint:146 pure tests прошли; directed PG11 routing/tracing/profile tests и16 API/bench tests проходили на промежуточном дереве; после расширения no-echo проверок23/25 проходили, два API-case упали из-за cached structlog/capsys test file, fixture исправлен и оба case вместе с API/legacy/cache проверками6/6 прошли. Это не full DoD доказательство окончательного дерева. Mypy255 и targeted ruff/format прошли; code/types сгенерированы только own checkout/scratchDB. Реальные LLM/Telegram/email не вызывались.

До done: обычное объединение maintenance checkpoint297a8459 и актуализация config fingerprint/preflight, narrow Setup UI key select/Save/Check+endpoint/scope, screenshots4варианта, полные lint/test/coverage и CI, human review конкретного DB/credential/external-budget diff. Persistent UTC RPD/attempt ledger остаётся отдельным T-050 P2/0014; numeric policies/customer money/HITL не менялись. Подробности в `docs/reviews/T-051-runtime-profiles.md`.


### UI source checkpoint (от83516b7)
Отдельная ветка `codex/T-051-profile-keys-ui`: существующий StepLLM получил selector api_key_id и компактный public key registry по generated API18. PATCH omission сохраняет binding, ID/null отправляются только по явному выбору, Check использует выбранный ID. Inactive/missing/provider/endpoint/scope ошибки не очищают binding и не включают env fallback. Unknown Giga default endpoint честно передан server-validation без подстановки URL. Password writeOnly/reset/GC, masked hints, safe errors, endpoint/scope при создании, DELETE409; profiles active/edit сохранены, несуществующий key PATCH не придуман.

Проверки UI:189 full frontend Vitest (19 target),4 production browser ru/en×light/dark на fake/local API, оба build/typecheck/ESLint green.4PNG отслеживаются в `docs/screenshots/T-051/`. Backend/contract/migrations не менялись, реальных ключей/внешних вызовов/DB writes нет. Producer maintenance composition, полный P1 DoD/CI/human review ещё обязательны; статус не закрыт. Подробности: `docs/reviews/T-051-profile-keys-ui.md`.
