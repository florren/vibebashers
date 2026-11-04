# T-198 — ограниченная запись настоящей кассеты сценария 11

Статус: **подготовлено и проверено offline; live не выполнялся**. Исторические
согласованные прогоны уже выполнены и не разрешают повтор. Перед `live` нужно
отдельное согласование передачи синтетического контекста и возможного расхода.

## Что закрывает пакет

У `social_sarcasm_escalation` нет настоящей кассеты. Обычный replay-тест честно
пропускается, а наличие только одной записи недостаточно: прежний тест разрешал
автоматический mock. Новый bounded recorder работает через фактический граф и
фиксированный маленький банк `backend/tests/fixtures/replay_bank_sarcasm_v1.json`.
Ответы модели не подменяются, не переносятся под другой hash, schema не ослабляется.

У существующих live normalize/classify используются templates v2; прежний replay
сохраняет v1. Добавлен только явный opt-in `LLMProfile.extra.agent_prompt_templates`
со значениями `v1|v2`; неизвестное значение отвергается до provider call. Default
прежний. Значение v2 выбирает уже существующие normalize/classify v2, decide v1.
Новых текстов prompts, API, DDL и финансовых правил нет. Сохранённый opaque `extra`
уже входит в profile snapshot; провайдер получает только `extra.request`, selector
не отправляется как отдельный параметр HTTP. Старые кассеты и request_hash неизменны.
В метаданных кассеты сохраняется обычный `prompt_version()`; точные template/source
hashes находятся отдельно в manifest, чтобы новая запись не объявлялась stale
только из-за нового произвольного имени версии.

## Данные, границы и учёт

[Полный план](T-198-replay11-bounded-plan.json) содержит fixture, schemas, все
preview messages, source hashes и payload sizes. Canonical JSON digest:
`b84e7e22db507fd0452633d4b4d2ac132ce67396e97d3faf539199e29f1c080c`.

- Одна модель `GigaChat-3-Pro`, только существующий `gigachat1` (`gigachat_env_1`).
- Максимум 6 inference (3 nodes × максимум2 попытки), 1 OAuth и 6 balance:
  не более13 HTTP. Provider/model/key fallback отсутствует.
- На запрос: максимум1024 output tokens,16000 characters/48000 UTF8 input bytes,
 65536 bytes полного JSON payload. Всего максимум6144 output tokens; timeout120s.
- Endpoints: штатные OAuth, `https://api.giga.chat/v1/balance` и `/chat/completions`.
  TLS включён, custom transport получает штатный TLS context с CA.
- В банк графа/чекпоинтов попадает только фиксированная синтетика. Это отдельная
  свежая БД `cx_replay11_*`, не текущий банк. CLI отвергает совпадение её имени
  с БД accounting; подготовка fixture не содержит production reset/drop.
- Live использует текущий **primary operational ledger**, прежние credential/profile
  identity и caps. Profile ID сохраняется в fixture projection. `live` не вызывает
  `connect_gigachat`, reconciliation, создание нового origin или обнуление counters.
  Сброс тестового банка не восстанавливает разрешение/лимит в отдельном ledger.
- Usage подтверждается штатным provider до закрытия попытки. Unknown сохраняется;
  следующие calls запрещаются до HTTP. Сумма расхода по тарифу заранее неизвестна:
  `actual_cost_rub=null`, `cost_known=false`, а не ноль.

Normalize первый request фиксирован: payload11402 bytes, input10743 bytes,
SHA256 `c8cd6bfa1ba2101a4d91fb3d5473746b7bc681c9c4bf05b11400e23974a1a55c`.
Classify/decide зависят от **валидированных реальных outputs** предыдущих nodes,
поэтому их окончательные live hashes до запуска неизвестны. Offline preview:
15979/18489 payload bytes;14932/17198 input bytes. В плане это явно помечено как
FAKE previews, не будущие live fingerprints. Guard проверяет actual payload,
размеры и допустимый correction suffix перед HTTP, provenance сохраняет actual hashes.

## Проверка и команды

`prepare` никогда не создаёт network transport: только `httpx.MockTransport`,
native PostgreSQL accounting и отдельный private fake maintenance namespace.
Фиктивные outputs хранятся исключительно под `FAKE-DO-NOT-PUBLISH`; в Git
публикуются только входной план и proof, не фиктивная кассета.

```bash
ENV_FILE=/dev/null APP_ENV=test PYTHONPATH=backend:. \
  backend/.venv/bin/python scripts/replay11_record.py prepare \
  --bank-dsn-file /private/0600-bank-connection.json \
  --output var/recordings/replay11-offline-new
```

БД должна быть новой и мигрированной штатным Alembic; CLI не мигрирует/сбрасывает
произвольную БД. DSN читается из private JSON с единственным полем `dsn`, секреты
не передаются в argv и не печатаются. Для live нужен private runtime env со штатными
primary accounting DSN/APP_SECRET/key и актуальным idle maintenance marker, а также
доступ к двум разным БД. `LLM_PROVIDER=gigachat` относится только к процессу recorder.

**Команда только для отдельного согласования, ещё не выполнялась:**

```bash
ENV_FILE=/private/runtime.env LLM_PROVIDER=gigachat PYTHONPATH=backend:. \
  backend/.venv/bin/python scripts/replay11_record.py live \
  --bank-dsn-file /private/0600-new-bank-connection.json \
  --output var/recordings/replay11-live-new \
  --plan docs/reviews/T-198-replay11-bounded-plan.json \
  --approved-plan-sha256 b84e7e22db507fd0452633d4b4d2ac132ce67396e97d3faf539199e29f1c080c \
  --profile-id EXISTING_PRIMARY_GIGACHAT_PRO_PROFILE_ID
```

Digest плана и manifest проверяются до выбора credential. Отдельный O_EXCL marker
по digest разрешает только один запуск этого плана. Output directory тоже exclusive;
ошибка не разрешает автоматический повтор. Нет автоматического копирования в
`data/cassettes`; после live нужны review actual provenance/response, строгий replay
на таком же fresh bank и changed-context miss. Частичные файлы failure сохраняются
в staging и не объявляются готовой кассетой.

Offline доказательства: **27 unit +3 actual PG composition =30 passed**. Раздельные
accounting/bank БД подтверждены:3known только в ledger,0wire в банке; после нового
банка strict replay без HTTP сохраняет ledger. Negative cases: cap2 → только2known;
ответ без usage →1unknown, дальнейший inference0. Три LLM nodes обязаны иметь
`status=ok` и источник `gigachat`/`replay`; append_mock выключен. Проверяются actual
sent clarification, scheduled followup, wake count1 и реальная escalation cx_lead,
а не только сохранённый decision. Изменение текста или выбор v1 даёт настоящий miss.

Фактическое [покрытие нового producer](T-198-replay11-coverage.json):168/184 AST
statement starts (91.30%), все5 новых selector lines исполнены. Это не branch
coverage и не обещание100% вероятностной валидности модели. Ruff/format и strict mypy
двух затронутых app modules прошли. Full backend unit:2296 passed/19 skipped (72.78s). Старый genuine v1 QR→Trace/Journey
и отдельный mock QR fast-path:2 passed11.74s. Полный final gate после композиции обязателен.

Этот же отдельно согласованный run проверит основной GigaChat со штатным retry2;
он не гарантирует, что оба реальных ответа модели всегда пройдут schema. Предыдущий
smoke с retry1 отклонил `route.co_teams=null`; schema/денежные policy не ослабляются.

## Откат

Удалить только новый неиспользуемый staging/fixture run по обычной операторской
процедуре после review. Удалять историю operational ledger нельзя. Кодовый откат
нового инструмента и opt-in selector не меняет старые кассеты/default templates;
новая v2 кассета без selector станет miss, а не будет искусственно rekeyed.
