# T-230: Unicode-цифры в поиске

`str.isdigit()` принимает надстрочные и обведённые цифры, которые `int()`
не разбирает. Например, `q=²` приводил к ValueError в общем parser вместо
текстового поиска. Условие заменено на `isdecimal()`; это сохраняет поддержку
Unicode decimal, например `١` и `１`, и нормализацию ведущих нулей.
Другие ветви parser, API/schema, SQL и ограничения длины не меняются.

Регрессии: четыре non-decimal digit строки остаются текстом, три decimal
варианта дают canonical number. Настоящий SQL search выполняет special-digit
запросы в READ ONLY транзакции; Arabic/fullwidth decimal дают те же hits,
что ASCII. Исходные assertions scope/неоднозначности/SQL injection сохранены.

Source `33de487d087f8b904bda2cb17b8774454635148e`:
`make test` exit0 — 1122 unit /18 skip, 238 integration /4 skip,
42 scenario /2 skip, 31 compliance, 173 frontend. Итого 1433 backend passed,
24 skipped. `make lint` exit0 — 173 frontend, Ruff352, mypy251,
OpenAPI drift191/191. Coverage actual grammar.py:28/28 executable statements,
100%, включая изменённое условие; 51 targeted cases под coverage passed1.78s.
Логи `/tmp/t230-unicode-{full-test,lint}.log`, coverage JSON
`/tmp/t230-unicode-coverage.json`.

После обычного merge main `d2a4026`:103 parser/fanout/startup unit passed3.01s,
5 PostgreSQL search/fanout passed55.84s, включая unchanged performance test.
Это дополнительный targeted run, не повторный полный прогон на новом составе.
Exact-head CI обязателен перед merge.

Выделенная БД `cx_t230_unicode_revision`, PostgreSQL16; реальных LLM/Telegram
не использовали. Исправлен конкретный crash; полная приёмка T-230, включая
самостоятельный benchmark поиска на10000сигналов, этим пакетом не заявляется.

## Актуальная композиция main2ed39d2

Обычный merge main2ed39d2 дал source77c712f. Обе части integration-файла сохранены: Unicode queries T230 и T017 `replay_bank` с проверкой актуального schema-hash/запретом rekey и нулём fallback/error. `backend/tests/conftest.py`, immutable `backend/tests/fixtures/replay_bank_v1.json` и данные cassette/golden не изменялись относительно main.

Новый bounded composed proof:103 parser/fanout/startup unit passed2.78s;11 actual PostgreSQL trace/journey/search/fanout passed55.71s, включая strict immutable replay, read-only enforcement, run isolation и unchanged performance assertion. БД толькоcx_t230_unicode_revision, акторов перед прогоном0, реальные LLM/каналы не использовались.

Make lint:188frontendpassed, Ruff366files/mypy257modules/drift192/192. Contracts45schemas/162paths, i18n1725keys, TS generation/205taskheaders идемпотентны. Это новый targeted proof, не повторный full backendrun: полный33de487 (1433backend/24skip+173frontend) остаётся source-specific. Exact-headCI/review/merge обязательны; полная T230 search10k benchmark приёмка по-прежнему не заявляется.
