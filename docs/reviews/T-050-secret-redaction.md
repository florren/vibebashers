# T-050 — единая secret boundary для application diagnostics

Пакет не меняет credentials, модели, rate/budget policy, banking/HITL, public contracts или user-visible exception responses. Env/реальные ключи/registry не читаются; все regression inputs synthetic. Это отдельный PR от streaming-enforcement packet.

## Подтверждённый дефект и граница исправления

В `configure_logging` отсутствовал secret processor: Authorization/api_key и nested headers уходили без маскирования в console и JSONL. `HttpStats.record` дополнительно сохранял текст исключения в ring buffer до structlog, поэтому одной обработки output было недостаточно: recent_errors API оставался отдельным местом хранения raw secret.

Чистый `observability.redaction` рекурсивно создаёт безопасную копию dict/list/tuple, маскирует известные credential field names без учёта регистра и поддерживает labeled Basic/Bearer/API-key текст, в том числе JSON-quoted, escaped и усечённые HTTP details. Результат idempotent; caller payload не меняется. Key hints/labels, token counters, request/business IDs и обычные routes сохраняются. Нет secret registry, original_payload side channel или дополнительного хранения исходных значений.

Processor стоит после `format_exc_info` и перед `JsonlSink`: formatted exceptions и один и тот же sanitized event идут в JSONL и console. HTTP error маскируется до append в ring buffer, а не только при чтении snapshot. JSONL rotation/retention не расширяются; старые файлы не переписываются.

Это application structlog boundary и существующий Uvicorn capability filter. Произвольные unlabeled строки, неизвестные объекты/форматы и сторонние custom debug handlers без этого pipeline не объявляются автоматически защищёнными. Маскирование логов не заменяет исключение raw provider responses/credentials из диагностики на границе внешних провайдеров. HTTP Problem response вне scope и не менялся.

## T119 capability URL: подтверждённый дополнительный путь утечки

Для неизвестного GET `/api/public/track/<token>/unregistered` `_route_template` возвращает raw path. `safe_public_path` уже защищал поле path, но route попадал в counter key, ring buffer и логирование без обработки. Это позволяло повторно показать capability в observability API даже при работающем Uvicorn access filter.

Тот же существующий tracking URL regex без изменения семантики вынесен в общий `redact_tracking_urls`; его используют PublicTokenFilter и text redaction. `HttpStats.record` применяет существующий safe_public_path к route/path ДО формирования counter key и ring buffer. Valid routes и их templates сохраняются; API shape и публичные ответы не меняются. Повторное masking уже безопасного `{token}` idempotent.

Regression выполняет actual ASGI GET неизвестного tracking route с synthetic capability и проверяет отсутствие token в console, JSONL, counter keys, ring buffer и snapshot. Дополнительно сохранены tests PublicTokenFilter и существующего safe_public_path; HTTP/body capture новых ПДн не добавляется.

## Проверки

37 targeted tests passed. Покрыты dev/prod console+JSONL, formatted exception, nested/mixed-case credentials, escaped/truncated strings, idempotence/nonmutation, сохранность hints/counters/business IDs, ring-buffer-before-retention и unknown-route capability. Ruff/mypy 248 прошли; полный `make lint` exit 0: format 339, frontend 144 passed, OpenAPI 191/191. Stdlib trace: 100% statement coverage нового redaction.py (38 executable lines) и app.logging (38 executable lines); новых зависимостей нет.

Полный `make test-unit` завершился exit 0: 953 passed / 18 skipped. Использованы локальные fake loopback/ASGI services, без внешних LLM/БД. Sandbox-запуск actual TestClient был остановлен на ожидании; тот же targeted suite вне sandbox прошёл за 0.23s. Полный DB/integration suite не входит в согласованный no-DB packet; `make licenses-check` прошёл: 526 distributions.

Root agent ведёт PR/CI/merge; самостоятельно remote actions не выполнялись. T050 остаётся in_progress: durable daily key counters/API synchronization, queue setting/head-of-line blocking и quota fallback policy — отдельные packets. Этот diff не закрывает всю карточку.

Логи: `/tmp/t050-redaction-targeted-final.log`, `/tmp/t050-redaction-full-unit.log`, `/tmp/t050-redaction-lint.log`, `/tmp/t050-redaction-coverage.log`, `/tmp/t050-redaction-licenses.log`. Машинная сводка: `/tmp/t050-redaction-verification.json`.
