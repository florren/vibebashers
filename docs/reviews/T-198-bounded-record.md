# T-198 — конкретный bounded egress plan для новой schema

Live не выполнялся и пока не разрешён. Этот пакет готовит reviewable CLI и MockTransport-проверки; отдельно нужны human contract review T014 и явное разрешение одного bounded запуска. Нельзя переносить старый ответ под новый request_hash.

## Проверенный источник и цель

Фиксирован только сценарий 8 `qr_fee_public_review`, модель `GigaChat-3-Pro`, prompt_version `v1.1`, immutable synthetic `replay_bank_v1`. Historical source request_hash — `174508311da29178f016ba3094e36291612a740c37427ff51ec4dedeede099a0`; recorded_at — `2026-10-28T07:30:44.410429+00:00`. CLI проверяет canonical SHA256 всей исходной записи, provider/model/scenario/version и frozen-bank source hash. На вход берутся только старые synthetic messages, а не старый response.

Текущая schema читается непосредственно из contracts через registry/deref. На исходном main `5b4be58` prefix6 ещё совпадает со старой schema: dry-run показывает `record_required=false`; `--run` отказывается до чтения ключей и HTTP. Предлагаемый T014 prefix9 меняет request_hash, поэтому после его обычного merge нужен новый реальный ответ. Контракт самостоятельно этим CLI не редактируется. Старые cassette bytes/provenance сохраняются.

## Команды и точные данные для review

Из `backend`: `.venv/bin/python -m app.replay.bounded_record --dry-run`. По умолчанию CLI также работает как dry-run. Он не читает env/credentials, не обращается к БД или сети; печатает request/schema/frozen-bank fingerprints, полные фиксированные messages и фактические wire_messages с JSON-инструкцией, schema, размеры и лимиты. Сохранённый JSON plan должен соответствовать reviewed commit.

Команда, которая предлагается для отдельного согласования (НЕ выполнялась):

```bash
ENV_FILE=/home/asb/vabebashers/vibebashers/.env APP_ENV=test PYTHONPATH=$PWD .venv/bin/python -m app.replay.bounded_record --run
```

Это явный direct-provider CLI; global LLM_PROVIDER/ProviderChain здесь не используются. Единственный credential — существующий GIGACHAT_AUTH_KEY_1, не ключ2 и не БД. Продукционные/тестовые БД вообще не используются. Другой URL/scope, TLS=false, отсутствующий ключ или уже существующий output-каталог дают отказ до сети.

## Возможные HTTP-запросы и бюджет

В проекте нет установленного GigaChat SDK: текущий provider использует httpx REST. Его поведение проверено по source. Отдельный guard ограничивает даже внутренние retry до inner transport:

- Максимум 3 HTTP-запроса суммарно: один POST `https://ngw.devices.sberbank.ru:9443/api/v2/oauth`, затем максимум два POST `https://api.giga.chat/v1/chat/completions`.
- Только scope `GIGACHAT_API_PERS`, одна модель `GigaChat-3-Pro`, один новый ApiKey в памяти. `/models`, `/balance`, token-count API, prepare/background refresh, другой key/model/provider и автоматический mock fallback отсутствуют. Redirect/другие endpoints отвергаются. Transport retries=0.
- Две inference-попытки разрешены только для correction структурированного ответа. HTTP401/403/429/500, unknown usage, неверная модель, превышение actual completion bound прекращают запись; нового внешнего запроса после такой ошибки нет.
- `stream=false`, temperature0, `max_tokens=1024` на запрос; максимум 2048 output tokens при двух попытках. Исторический корректный ответ занимал 654 completion tokens; лимит 1024 оставляет запас, но успех/отсутствие truncation не гарантируются, schema не ослабляется.
- Полный текст messages, включая JSON Schema и correction после первого ответа, ограничен 16000 characters/48000 UTF8 bytes на запрос; весь JSON payload≤64000 bytes. Повтор с превышением cap блокируется до HTTP. Общий generation timeout 30s, внешний timeout 35s. В первом dry-run точные размеры выводятся отдельно.
- Денежный расход в рублях заранее не известен и не считается нулевым. USD budget OpenRouter к GigaChat не применяется. Объём egress ограничен числом запросов и размером input/output; это не обещание конкретной цены или доступности квоты. Никакого дополнительного запроса ради баланса/тарифа нет.
- Нужны подтверждённые integer usage.prompt_tokens/completion_tokens/total_tokens. Их отсутствие прекращает дальнейшие inference и не становится нулём. Сохраняются observed totals всех полученных ответов, включая failed validation; HTTP-error оставляет `usage_unknown=true`. Стоимость `actual_cost_rub=null`/`cost_known=false`, а не искусственный ноль из zero-price профиля.

Проверка TLS остаётся включённой: custom AsyncHTTPTransport получает существующий TLS context с bundled/configured CA. По installed httpx source verify из AsyncClient не перенастраивает переданный transport, поэтому context передан именно transport.

## Результат и безопасность хранения

Только новый валидный response сохраняется в новый `var/recordings/T-198/gigachat.jsonl`; sibling `provenance.json` содержит hash источника, schema/target hashes, версию, размеры, usage и фактические counters. Каталог создаётся exclusive; повторный запуск при существующем каталоге отвергается до HTTP. Основной `data/cassettes/gigachat.jsonl` не переписывается и не дополняется автоматически. При ошибке нет нового cassette response; остаётся безопасный provenance. Публикация staging-кассеты и обновление replay-bank selection потребуют отдельной проверки actual нового ответа offline-сценариями.

Headers/ключи/access token/raw errors не попадают в отчёт; ошибки upstream заменяются безопасным кодом перед logger провайдера. Credential reflection в input/успешном response блокируется. Старые real responses не превращаются в новые, mock output не публикуется как live: все mock записи тестов находятся только в pytest temporary directories.

Официальные источники: [авторизация и текущий API URL](https://developers.sber.ru/docs/ru/gigachat/api/reference/rest/gigachat-api), [генерация ответа и коды ошибок](https://developers.sber.ru/docs/ru/gigachat/api/reference/rest/post-chat), [назначение max_tokens](https://developers.sber.ru/help/gigachat-api/prompt-engineering). Retry/caps и размеры выше — факты нашей реализации, не обещания SDK или тарифа.

## Проверки независимого CLI

До merge T014: 68 targeted unit passed (bounded CLI, cassettes, auth refresh/cold start), Ruff и mypy 246 passed. Coverage нового модуля измерена stdlib trace (pytest-cov не установлен), предварительно 91%; итог фиксируется после source freeze. Live, реальные OAuth и inference не выполнялись. Полный green replay DoD до нового одобренного ответа не заявляется.


## Совместимость prefix 6 → 9 и порядок миграции

T014 `a33b552` добавлен обычным merge после независимых CLI tests; контракт был подготовлен родительским агентом и ещё требует human review. На schema prefix6 record_required=false/0HTTP, на точном новом contract prefix9 record_required=true. Сохранённый `T-198-bounded-record-plan.json` даёт target request_hash `9c3165dd136da8c44a1d7a12f9e8efef634cda375fb015f3435373e4f8abe903`, schema SHA256 `02f49c4b9abaafe1ca12f9c8195e6805ef9f4bfd6b6360f8704aa5f62044b0f9`. Фактический первый input: 10593 characters/12827 UTF8 bytes; JSON payload 14024 bytes. Metadata и полные wire_messages доступны для human review без ключей/сети.

После отдельного разрешения bounded запуска и успешного нового real response требуется проверить staging usage/provenance/schema, затем опубликовать его отдельным новым cassette-файлом, сохраняя старый файл byte-for-byte. Frozen replay bank должен искать фактическую запись для актуального computed hash; historical source_request_hash остаётся provenance. Если новой реальной записи нет, strict replay продолжает отказывать: нельзя заменять его mock-успехом, rekey старого ответа или ослаблением assert. Затем нужны offline сценарии 8/12 с ledger/trace evidence; основной CassetteStore.get/request_hash не менялись.

## Итог проверки подготовленного CLI

После T014 merge: 139 targeted unit passed; полный `make test-unit`: 930 passed/18 skipped, exit 0. Финальный `make lint`: exit 0, Ruff/format 334/mypy 246, frontend 144 passed, OpenAPI 191/191. `make licenses-check`: 526 distributions, exit 0. Новый module: 38 tests passed под stdlib trace, statement coverage 92% (294 executable lines). pytest-cov отсутствует, новых зависимостей ради измерения не добавлено.

Первый полный unit запуск был остановлен в sandbox на штатном health loopback-тесте; повтор с доступом к локальным fake services прошёл полностью. Логи: `/tmp/t198-targeted-final.log`, `/tmp/t198-full-unit-final.log`, `/tmp/t198-lint-final.log`, `/tmp/t198-coverage-final.log`, `/tmp/t198-licenses.log`. Новых OAuth/inference не выполнялось; output-каталог live не создавался. Полный replay DoD/make test зелёным не заявляется до одобренной новой реальной кассеты; известный strict schema freshness blocker описан в `T-014-error-code-contract.md`.
