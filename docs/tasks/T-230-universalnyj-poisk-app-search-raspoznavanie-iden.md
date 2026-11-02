# T-230 — Универсальный поиск app/search: распознавание идентификаторов, подсказки клиента, полнотекстовый поиск; GET /api/search

| Поле | Значение |
|---|---|
| Эпик | E23 Поиск и след объекта [АРХ] |
| Субагент | `SA-Trace` (модель следа, поиск, путь обращения [АРХ]) |
| Оценка | M (1–2 дня) |
| Волна | 8 |
| Слой | `L3` Агент и контуры (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `todo` |

## Цель
Найти объект по любому идентификатору или тексту (ТЗ 28.2) быстро и без ПДн.

## Разделы ТЗ (docs/TZ.md)
§28.2, §28.6, §28.7, §16.4

## Контракты
- `events/trace/search_response.schema.json`
- `api/openapi.yaml: GET /api/search`

## Зависимости
- Зависит от: [T-223](T-223-kontrakty-sleda-i-poiska-migraciya-0004-openapi.md), [T-005](T-005-primenenie-schema-sql-sqlalchemy-modeli-sessii.md)
- Блокирует: [T-231](T-231-globalnyj-poisk-v-interfejse-stroka-v-shapke-ctr.md), [T-235](T-235-scenarij-13-poisk-i-sled-yaml-e2e-po-vsem-tipam.md), [T-267](T-267-nepreryvnost-signalov-i-informacii-operatora-hit.md)

## Что сделать
1. `backend/app/search/grammar.py`: таблица префиксов и форматов из ТЗ 28.2 (SIG, INC, CL, POST, TR, ESC, AS, EMP, AR, SR, TSK, NTF, LED, HD, FUP, CSI, VSP, RULE, коды ошибок, UUID, токен трекинга, `@ник`, маска карты и телефона, только цифры), нормализация регистра, пробелов, дефисов и ведущих нулей.
2. Поиск: точное совпадение по `public_id` и ключам; подсказки клиента (синтетика, в масках) → клиенты и их сигналы; число без префикса → кандидаты по типам; текст → `tsvector('russian')` + `pg_trgm` с ранжированием и фрагментом совпадения.
3. Режимы `run_id=current|all|<id>`: идентификаторы глобальны (`all`), текст — текущий запуск и baseline; чип запуска в каждой строке.
4. Маскирование результата и защита от инъекций (параметризованные запросы); `took_ms` в ответе; роутер `backend/app/api/search.py`.
5. Тесты: по одному кейсу на каждый тип идентификатора, неоднозначные числа, текстовый поиск с опечаткой, 10 000 сигналов и p95 ≤ 300 мс, отсутствие сырых ПДн в ответах.

## Критерии приёмки
- [ ] Каждый идентификатор из ТЗ 28.2 находит объект; неоднозначный ввод возвращает кандидатов с типами.
- [ ] p95 ≤ 300 мс на профиле demo (требование ЕТЗ ≤ 500 мс выполняется с запасом).
- [ ] Результаты не содержат реальных ПДн, телефоны и карты в масках.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/integration/test_search.py backend/tests/unit/test_search_grammar.py
curl -s 'localhost:8000/api/search?q=sig%20123' | jq '.parsed, .hits[0]'
```

## Отчёт субагента
Грамматика всех префиксов, UUID/токена/подсказок/чисел; параметризованный поиск public_id, FTS russian и pg_trgm; run scope, маскирование и took_ms. Учтён действующий справочник ВСП с code=0042, наружу возвращается VSP-0042. Полный нагрузочный прогон 10 000 сигналов не проводился.

Ветка: `codex/journey-trace`; пакет T-224/T-231/T-232/T-225/T-230/T-226/T-233. `cross-layer` согласован пользователем. Контракты T-223 и механизм денег/HITL не изменялись.

Проверки: `make lint`, `make test` (461 unit / 86 integration / 22 scenario passed; 20 skipped), contracts, OpenAPI drift, owners --allow-cross и i18n — успешно. Новые backend-пакеты: coverage 94% (45 targeted tests). Frontend: typecheck, lint, build, 39 vitest и 4 Playwright — успешно. Скриншоты ru/en × light/dark: `docs/screenshots/trace-journey/`. Локальная тестовая PostgreSQL 18.6 с UTC; PostgreSQL 16 проверяется CI. Node 26 требует `NODE_OPTIONS=--no-experimental-webstorage` для существующих jsdom-тестов; CI использует Node 22.

Сценарии 12/13 добавлены как YAML-манифесты модели чтения; проверки сценариев 1/8/11 на записанных mock-данных и отдельный replay сценария 8 проходят. Эти YAML не создают новый запуск агента из UI. Новый live-прогон GigaChat не выполнялся. Полная приёмка дополнительных требований карточек за пределами указанного пользователем среза не заявляется.


### Audit followup T-234 (2026-11-02)
Подтверждено: `app.search.grammar.parse('²')` вызывает `ValueError`, потому что `str.isdigit()` шире множества символов, принимаемых `int()`. Это общий parser gap для Search/legacy Trace, требует согласованной контролируемой обработки malformed numeric input и regressions decimalUnicode/overflow/empty; новую карточку не создавали, статус T-230 не закрывается этой правкой. В T-234 защищён только новый `/relations` boundary до DB/LLM; общий parser и старые API намеренно не менялись. Подробности: `docs/reviews/T-234-trace-graph-verification.md`.
