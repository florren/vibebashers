# T200/T004: версия runtime OpenAPI из канонического контракта

Проверенная регрессия: `create_app().openapi()["info"]["version"]` возвращал
`1.4.0`, когда канонический `contracts/api/openapi.yaml` уже содержал `1.5.29`.
Старая проверка drift сравнивала пути и методы и пропускала расхождение.
Первоначальный regression завершился `1 failed in 1.80s`.

FastAPI теперь получает версию из небольшого cached loader канонического YAML.
В репозитории файл расположен в `contracts/api/openapi.yaml`; Docker COPY
размещает его в `/contracts/api/openapi.yaml`. ROOT корректен для обоих layout.
Чтение кэшируется на процесс; code и contracts обновляются вместе с перезапуском.
Missing file, invalid YAML, отсутствующий, нестроковый или пустой `info.version`
дают явный отказ. Исключения не кэшируются.

`check_openapi_drift` дополнительно сравнивает `app.version` с `info.version`,
включая режим `--tags`. Version-only mismatch возвращает exit1 при совпадающих
маршрутах. Канонический API, DTO, пути, DDL и настройки этим исправлением не
меняются. Проверку всех форм ответов скрипт по-прежнему не реализует: его область —
пути, методы и metadata version.

Проверки runtime на base `1d248e2`:

- После исходного RED: 9 целевых проверок прошли за 2.76s. С actual ASGI
  `GET /openapi.json` — 10 passed за 16.91s под timid tracer; дополнительный
  version-only checker — 1 passed за 10.88s. Покрыты все 17 новых executable lines
  (100%), включая helper 12/12. Это покрытие, не измерение latency.
- Ruff/format изменённых app/test files и syntax-critical script checks прошли;
  mypy проверил 324 source files. Drift: 196/196 для всего API и 27/27 для
  health/settings, `missing=0 extra=0`. Генератор карточек идемпотентен.
- Дополнительный full Ruff для исторически не входящего в `make lint` script
  возвращает исходные пять diagnostics: EXE001 ×1 и RUF100 ×4. Baseline и current
  проверены с одинаковым stdin-filename; новых diagnostics нет. Общая стилеправка
  этого файла в bugfix не включена.
- Независимое A3 review не нашло замечаний: 8 tests passed за 2.74s, отдельно
  проверены missing/malformed → valid recovery и успешное кэширование.
- В собственном actual API30 image `b98d406e` новый helper смонтирован read-only.
  Одноразовый контейнер `--read-only --network none` подтвердил
  `api_version() == "1.5.30"`. БД и actors не запускались. Это проверка layout
  и следующей версии через один file overlay; полного нового image build не было.

[Точные hashes и покрытие](T-200-runtime-version-proof.json).
Полный exact-head CI обязателен перед merge; локальный полный `make test` не
заявляется. Persistent data не затрагиваются. Откат кода вернёт прежнюю неверную
metadata. Live LLM, Telegram, STT и production не использовались.
