# T-235 — Сценарий 13 «Поиск и след»: YAML, e2e по всем типам идентификаторов, автотесты «только чтение»

| Поле | Значение |
|---|---|
| Эпик | E23 Поиск и след объекта [АРХ] |
| Субагент | `SA-QA` (тесты и CI) |
| Оценка | M (1–2 дня) |
| Волна | 9 |
| Слой | `L5` Качество (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `in_progress` |

## Цель
Автоматическая приёмка поиска и следа (ТЗ 18, сценарий 13; критерии 44–45).

## Разделы ТЗ (docs/TZ.md)
§18, §28.8, §19

## Контракты
- `data/scenarios/13_search_trace.yaml`

## Зависимости
- Зависит от: [T-230](T-230-universalnyj-poisk-app-search-raspoznavanie-iden.md), [T-232](T-232-ekran-sled-trace-kind-ref-do-obekt-posle-itog-oz.md), [T-233](T-233-sled-adaptery-kartochki-obekta-i-rendery-sobytij.md)
- Блокирует: [T-260](T-260-dokumentaciya-v1-5-demo-skript-bloki-e-f-rukovod.md)

## Что сделать
1. `data/scenarios/13_search_trace.yaml` (ID сценария 13): набор запросов по каждому типу идентификатора, ожидаемые типы и цели, два следа с проверкой «до/объект/после/итог», веерный инцидент (сценарий 6), инцидент в работе с ожидаемым шагом.
2. Автотесты backend: матрица идентификаторов, ПДн-проверка выдачи (`test_no_pii`), бюджеты времени, тест «только чтение» (нет write-эндпоинтов у `search`/`trace`/`journey`, LLM не вызывается).
3. Playwright: ввод запроса, выбор кандидата, переход «до → объект → после», экспорт JSON/Markdown, скриншоты.
4. Блок E демо-скрипта, часть 2 (поиск); пункт в меню демонстратора.

## Критерии приёмки
- [ ] `make scenario ID=search_and_trace` зелёный на кассетах.
- [ ] Все типы идентификаторов из ТЗ 28.2 покрыты; нет реальных ПДн.
- [ ] Тест «только чтение» красный при добавлении записи в обработчик следа.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
make scenario ID=search_and_trace
cd backend && .venv/bin/pytest -q tests/integration/test_search_trace_acceptance.py
cd frontend && npx playwright test e2e/trace-journey.spec.ts --project=read-only
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._

## Ревизия: проверка записанных объектов и scope алертов

Ветка `codex/T-235-search-trace-acceptance`. CLI больше не считает HTTP 501 успехом.
Прогон `all` продолжает остальные сценарии и возвращает код 1 при любой ошибке.
Для `search_and_trace` выполняются настоящие GET search/trace вместо запуска
агента: 17 префиксов и 9 форматов из manifest, с явным `run_id=all`. Отсутствующие
объекты, неверные DTO/совпадения, HTTP/network failures и отражённый tracking token
дают FAIL. Контакты и capability tokens не выводятся в диагностике. Объекты
выбираются SQL в READ ONLY REPEATABLE READ с `statement_timeout=3s`.

Actual ASGI/PG проверка обнаружила ошибку `scope("alert")`: у `compliance_alerts`
нет `run_id`. Теперь scope берётся через родительскую `audio_sessions`. Проверены
собственный/чужой запуск и 404 для чужого алерта. API, DDL и денежные политики
не меняются.

Checkpoint: 20 адресных unit/PG тестов прошли за 11.93s под coverage. Все 43 actual
API requests — GET (26 search + 17 trace); вызовов LLM нет. Зарегистрированные
search/trace/journey routes допускают только GET/HEAD. Контрольный INSERT внутри
Trace отклоняется PostgreSQL с ReadOnlySqlTransaction, строка не создаётся.
Граф теста явно помечен `synthetic-search-fixture`/`deferred`; он не изображает
завершённый LLM run. Сигналы проходят normalizer, проводки — штатный Mock-АБС helper.
Ruff/formatter изменённых файлов прошли; assertions не ослаблены.

Карточка остаётся `in_progress`: rich traces, fanout, pending, performance,
расширенные проверки ПДн, браузер, screenshots/export, DEMO-SCRIPT и полный
suite/CI/merge ещё требуются. Реальных LLM/Telegram вызовов нет. Cross-layer
L1 scripts/docs, L3 trace, L5 tests согласован общим поручением пользователя;
нового contract-change нет.

Следующий checkpoint: два причинных следа, pending и fanout120 проверены actualPG;
всего 47 GET. Меню сценария 13 открывает read-only Trace, добавлены локальные
JSON/Markdown exports со scope и экранированием текста. Некорректные внутренние
числовые refs/UUID дают 422 до SQL. Проверки: 46 unit/PG (7.79s), 329 frontend
(10.14s), lint/typecheck, main/personal builds. Actual browser и полный backend/CI
ещё требуются; прежний coverage artifact относится только к c4d53ab.


## Финальная локальная проверка d1a4197

Последовательный `make test`: 1410 unit / 18 skip, 284 integration / 2 skip,
43 scenarios / 2 skip, 31 compliance; всего 1768 backend passed / 22 skip,
329 frontend passed. `make lint` зелёный: frontend lint/types/tests,
Ruff/formatter 377 файлов, mypy 258, drift 192/192. Runtime после этого source
не менялся. CI и merge остаются отдельными gate.

Финальное покрытие: 46 targeted unit/actual PG tests за 12.92s,
146/152 новых исполняемых строк (96.05%), hashes и строки в
`T-235-final-coverage.json`. Первый coverage-прогон остановился на setup:
системный pg_dump18 несовместим с PG16. Повтор с локальным PG16 client прошёл;
тесты/assertions не менялись.

Actual localhost HTTP benchmark на отдельном PostgreSQL16.15: demo5000,
600000 операций, PostgreSQL ограничен 4 CPU / 2GiB, API/client закреплены
на тех же четырёх CPU. 47 запросов проверены до замера, затем по25 повторов:
1175 timed GET, всего1222. Все47 p95 меньше300ms; худший132.993ms.
84 streaming table fingerprints совпали до/после; structured LLM и external
network guards не сработали. Seed включая dump занял22.509s. Детали по каждому
запросу: `T-235-demo5000-performance.json`. Это последовательный actor-free
замер после validation warmup, не доказательство задержек под активным Sim.
Временные API/PG остановлены; рабочая БД не использовалась.

Actual browser proof остаётся source-qualified ae7141d (10 вариантов), CI
Playwright — четыре mocked API cases; различие описано выше. Replay-корпус
с законченными native agent traces и нагрузка активного Sim остаются зависимыми
приёмочными условиями; карточка не закрывается фиктивно.
