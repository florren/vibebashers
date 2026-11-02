# T-050 — enforcement существующего rate limiter для streaming

Подготовлено для конкретного review бюджета внешних API до merge. Это не банковские деньги: refund/HITL, финансовые лимиты и права оператора не затронуты. Public contracts, схема БД, catalog/model defaults и значения RPM/RPD/timeout не менялись.

## Подтверждённый пробел

T050 п. 1 и ТЗ 16.4 требуют проводить LLM-вызовы через rate limiter. Structured ProviderChain уже вызывает acquire, а stream прежде сразу вызывал provider.stream. Изолированный synthetic probe на main `5075355`: при заранее исчерпанном rpd=1 live candidate был вызван и отдал текст; HTTP-запросов не было. Поэтому UI streaming обходил тот же лимит, который блокировал structured request.

## Конкретное изменение

- Перед каждым live streaming candidate вызывается существующий limiter.acquire с теми же profile.code/rpm_limit/rpd_limit. Mock/replay не тратят квоту; explicit offline profile по-прежнему не вызывает live-provider.
- Deadline кандидата включает ожидание слота и весь streamed I/O. В provider передаётся оставшийся бюджет, а получение каждого чанка ограничено этим же deadline. Новых значений timeout или rate policy нет.
- До первого чанка ошибка/квота/timeout ведёт к прежнему порядку fallback. После первого чанка источник закрывается без нового live/mock fallback, чтобы не склеивать ответы разных моделей. Caller cancellation не поглощается.
- При закрытии/отмене underlying async iterator освобождается. Таймер стоит на await anext, а не вокруг yield: он не отменяет task потребителя между чтением чанков. Если deadline уже прошёл, следующий anext завершает partial stream без нового fallback.

Это enforcement установленной квоты: число ранее разрешённых существующим limiter запросов не увеличивается. Профили, ключи, model routing и main→fast policy не меняются. Счётчик резервируется перед live attempt так же, как в structured path; это не новая модель реального provider billing.

## Проверки и оставшийся объём T050

53 targeted tests passed: `test_ratelimit.py`, `test_llm_chain.py`, `test_llm_routing.py`. Проверены реальные in-memory RPM/RPD exhaustion, каждый live candidate, offline bypass, ожидание/таймаут, deadline после ожидания, partial failure, cancellation/consumer close и отсутствие отмены consumer между чанками. Все providers synthetic/MockTransport; никаких реальных credentials/LLM/БД.

`make lint` exit 0: Ruff, format 337, mypy 246, frontend 144, OpenAPI 191/191. Stdlib trace для failover.py: 82% statement coverage (316 executable lines); те же 53 tests passed под instrumentation. pytest-cov отсутствует, зависимости не добавлялись.

Карточка T050 остаётся in_progress: durable daily key accounting/актуальные API counters, queue default 20s против существующих 5s, global-lock head-of-line blocking, main429→fast policy и единый secret log filter этим packet не закрываются. Их нельзя молча объявить реализованными из-за наличия token bucket. Read-only аудит: `/tmp/t050-t047-readonly-audit.json`.

Отдельно catalog: T047 — GigaChat pool; OpenRouter availability относится T048/ТЗ 5.2. Deactivation plan и startup sync уже существуют. Два 404 в approved bounded smoke не доказывают отсутствие sync или удаления model ID; нужны отдельные данные о каталоге/доступности. В этом diff нет ни GET каталога, ни автоматических замен моделей.

Полный `make test-unit`: 925 passed / 18 skipped, exit 0. `make licenses-check`: 526 distributions, exit 0. Полный DB/integration make test в согласованном без-DB packet не запускался. До merge нужен human review конкретного enforcement diff; root agent ведёт PR/CI/merge. Rollback — обычный revert packet, без миграции/удаления данных; он вернёт прежний quota bypass для stream, поэтому это не предлагается как обход лимита.

Логи: `/tmp/t050-targeted.log`, `/tmp/t050-full-unit.log`, `/tmp/t050-lint.log`, `/tmp/t050-coverage.log`, `/tmp/t050-licenses.log`; машинная сводка `/tmp/t050-stream-verification.json`.

## Проверка композиции с main 34e39ef

Обычный merge сохраняет SDK/budget, финансовые defaults и golden corpus. 53 targeted tests; make lint exit0 (163 frontend, Ruff/format350, mypy250, OpenAPI191/191). contracts44/161, owners L1 и diff-check green. Полная remote CI проверяет итоговый head; приведённые выше полные unit runs относятся к явно указанным предыдущим исходным версиям. Новых внешних вызовов не было.
