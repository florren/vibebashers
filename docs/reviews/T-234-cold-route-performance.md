# T-234 — холодный первый запрос: CI performance followup

PR172, backend shard2: неизменённый `test_large_fan_page_latency_and_bounded_response` обнаружил p95=344,189825мс при требовании <300мс. Локальные предыдущие114мс не считались опровержением CI. Порог/10001член/page50/10samples/первыйGET/readonly assertions не менялись, warmup/skip в тест не добавлялись.

## Измеренная причина

Pinned/installed FastAPI0.159.1 (`backend/uv.lock`) лениво строит effective include-contexts при route matching. Whole-ASGI cProfile первого GET:385430вызовов/150мс, из них131мс — построение191 route-context и509Pydantic TypeAdapter. У warm-запроса18899вызовов/16мс. Профиль только handler/SQL ошибочно не видел бы эту стоимость.

`EXPLAIN (ANALYZE,BUFFERS)` выполнен исключительно для SELECT в READ ONLY транзакции own scratch БД. Count10001:1,596мс (SeqScan обоснован выборкой почти всей маленькой fixture-таблицы). Страница51:0,235мс, bounded PK IndexScan/MergeJoin+LIMIT. SQL не является узким участком и **не менялся**.

## Исправление

В конце `create_app`, после API/WebSocket/frontend routes, вызывается публичный `app.openapi()`. Это eager compilation статических route/dependency/schema metadata до readiness, не выполнение HTTP, handlers, dependencies или чтение entity data. Private FastAPI APIs не вызываются, версия библиотеки не меняется. В проекте нет custom OpenAPI override/static schema, обходящего compilation; before/after cProfile подтвердил реальную материализацию контекстов.

Цена переносится в создание приложения: пять cold creations135–266мс. После каждой из них **первый** GET10001/page50 без явного warmup занимает13,1–14,2мс; отдельный первый healthyGET `/api/health`29,0мс. Отпечатки всех85таблиц совпали, BombLLM0. Новый whole-ASGI первый GET:25666вызовов/19мс, построение191контекста исчезло из request path. Cached metadata не кеширует данные/результаты dependencies; dependency overrides по-прежнему разрешаются на запросе.

## Проверка

-70 targeted unit/PG passed42,57с: новый metadata startup regression, dynamic route/schema, late dependency overrides, healthy/degraded health, existing scaffold/WS/quality, все ref/fullN/scope/privacy/real1/6/8 cases.
- Неизменённый strict performance test: p95=53,67мс в targeted suite; повторный отдельный прогон54,19мс, Python request peak260836B. Первый GET включён, page50/total10001/response-size/readonly сохранены.
- Ruff356files/format и mypy255source green; schemas/contracts/DTO/SQL не менялись. Полный20-минутный backend suite повторно не запускался; **точный новый SHA должен пройти CI**, локальное измерение не объявляется подтверждением runner SLO.
- Создание приложения не выполняет route/dependency handlers; поздний DELETE test route обновляет публичную schema и вызывается. Overrides get_session после compilation дают как healthy, так и degraded200 без реальнойБД/LLM в unit. Отдельный здоровыйPGhealth checked на scratch.

Артефакты только `/tmp`, production logging не менялся:
`vibebashers-t234-plan-{before,after}.json`, `vibebashers-t234-route-{before,after}.json`, `vibebashers-t234-asgi-{before,after}-1.txt`, `vibebashers-t234-cold-after.json`, `vibebashers-t234-{startup-perf-targets,perf-fixed,perf-lint,perf-mypy}.log`. После fix новые firstGET samples из пяти свежих приложений сохранены отдельно от pytest samples; оба вида измерения названы явно.
