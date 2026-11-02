# Лицензии сторонних компонентов

| Компонент | Лицензия | Источник / путь в репозитории |
|---|---|---|
| Inter | SIL Open Font License 1.1 | https://github.com/rsms/inter — бинарники `frontend/public/fonts/inter-*.woff2`, notice `frontend/public/fonts/Inter-OFL.txt` |
| JetBrains Mono | SIL Open Font License 1.1 | https://github.com/JetBrains/JetBrainsMono — `frontend/public/fonts/jetbrains-mono-*.woff2`, notice `frontend/public/fonts/JetBrainsMono-OFL.txt` |

Шрифты поставляются локально (без CDN и без npm `@fontsource/*`), см. `data/README.md` и карточку T-263.

### CSI import (T-246)

- openpyxl 3.1.5 — MIT, [PyPI / upstream](https://pypi.org/project/openpyxl/); чтение XLSX read-only и запись XLSX-отчётов T-244.
- et-xmlfile 2.0.0 — MIT, [upstream](https://pypi.org/project/et-xmlfile/); зависимость openpyxl.
- defusedxml 0.7.1 — PSF License, [upstream](https://pypi.org/project/defusedxml/); защита XML при чтении пользовательских XLSX (рекомендация upstream openpyxl).

### Публичные сертификаты GigaChat

`backend/app/llm/certs/` содержит общедоступные X.509 сертификаты НУЦ Минцифры с gu-st.ru и их объединение `gigachat-ca.pem`. Это публичные сертификаты, не закрытые ключи и не новые программные зависимости. Источники, SHA-256 fingerprints и даты действия — в README каталога. Системное хранилище доверия и certifi не модифицируются; цепочка добавляется только в SSLContext клиента GigaChat.

### Инструменты baseline (T-270)

postgresql-client-16 (pg_dump, pg_restore, libpq) — PostgreSQL License, [официальная лицензия](https://www.postgresql.org/about/licence/). Устанавливается в Docker через подписанный [официальный PGDG](https://www.postgresql.org/download/linux/debian/), Debian bookworm; версия сервера остаётся 16. Python/npm-зависимости не добавлялись.

### OpenAI-compatible SDK (T-048)

- openai 2.54.0 — Apache-2.0, [официальная библиотека](https://github.com/openai/openai-python); версия фиксируется `backend/uv.lock`.
- distro 1.9.0 — Apache-2.0; jiter 0.18.0 — MIT; sniffio 1.3.1 — MIT OR Apache-2.0; транзитивные зависимости SDK, лицензии проверены по metadata установленных wheel. Остальные зависимости уже присутствовали в lock.
## Полный inventory и gate (T-152)

[`THIRD_PARTY_LICENSES.md`](../THIRD_PARTY_LICENSES.md) генерируется из обоих lock-файлов и version-bound Python metadata: 113 Python и 437 npm записей (runtime/dev, включая platform-only distributions). `make licenses-check` не обращается к сети и требует актуальности отчёта. Новая/изменённая версия без metadata, неизвестный SPDX identifier, неоднозначная строка `SEE LICENSE`, `UNLICENSED` и непроверенный `WITH` завершают проверку ошибкой. `AND`/`OR` и скобки разбираются структурно; известная разрешённая ветка `OR` может быть выбрана, неизвестная ветка никогда не игнорируется.

Python evidence: `docs/licenses/python-metadata.json` сохраняет исходные поля METADATA, SHA-256 license notices и источник. Для platform-only colorama/jaraco-functools/tzdata wheel скачаны из официального PyPI без установки; SHA-256 каждого архива сверен с `uv.lock`. Для legacy Jinja2 3.1.6 (BSD-3-Clause), qrcode 8.2 (BSD-3-Clause AND MIT) и colorama 0.4.6 (BSD-3-Clause) текст notice проверен адресно. Повтор сбора: `backend/.venv/bin/python scripts/collect_license_metadata.py --wheel-dir /path/to/downloaded-wheels`; collector проверяет hash wheel по lock и не скачивает/устанавливает зависимости. Затем `backend/.venv/bin/python scripts/licenses_check.py --write`. Новые legacy-варианты требуют явной проверки их notices, не наследуют разрешение по имени пакета.

**GPL-конфликт устранён:** pglast 8.7 имел `License-Expression: GPL-3.0-or-later` в METADATA. Удалён только этот dev-инструмент; проверка SQL передана настоящему PostgreSQL 16: CI job `db` применяет schema.sql и каждый файл `contracts/db/migrations/*.sql` дважды. Синтаксическая проверка не подменяется лексическим форматтером. Остальные версии uv.lock сохранены.

psycopg 3.3.6, psycopg-binary 3.3.6 и psycopg-pool 3.3.3 объявляют **LGPL-3.0-only**. LGPL — отдельная лицензия, она не блокируется ошибочным substring-поиском `GPL`. Исходные LICENSE/notices этих distributions сохраняются в установленных пакетах; их SHA-256 внесены в evidence. Gate запрещает GPL/AGPL/SSPL и не включает source-available лицензии в разрешённый список. Inventory относится к Python/npm distributions из lock; это не SBOM операционной системы Docker-образа и не заменяет notices, поставляемые самими distributions.

### Ручной реестр ресурсов

- Inter и JetBrains Mono: OFL-1.1; полные notices рядом с `.woff2` в `frontend/public/fonts/` (см. таблицу выше).
- Карта `frontend/src/shared/geo/russia-regions.topo.json`: исходный набор `codeforamerica/click_that_hood`, геоданные © OpenStreetMap contributors, ODbL-1.0; происхождение и преобразования описаны в [geo/README](../frontend/src/shared/geo/README.md). Это лицензия геоданных, отдельно от MIT-кода источника.
- Иконки lucide-react, d3-geo/topojson-client, ECharts: точные версии и SPDX берутся из npm inventory; внешние CDN не используются.
- Vosk Python package: Apache-2.0 по METADATA classifier; SHA license notice сохранён в Python evidence. Модели STT учитываются отдельно в `data/models/stt/README.md`; inventory wheel не является проверкой скачанного model archive.
- Синтетические корпуса и справочники: происхождение в [data/README](../data/README.md); публичные TLS-сертификаты и PostgreSQL client tools описаны выше.

### Telegram transport (T-121)

`aiogram 3.31.0` — MIT. Его aiogram/aiohttp окружение изолировано в
`tgbot/pyproject.toml` и `tgbot/uv.lock`: aiogram требует Pydantic <2.14,
backend сохраняет собственный Pydantic 2.14.1. Не понижаем зависимости backend.
Все36 runtime/dev/platform-only distributions проверены по version-bound METADATA
и license notices: `docs/licenses/tgbot-metadata.json`,
[`tgbot/THIRD_PARTY_LICENSES.md`](../tgbot/THIRD_PARTY_LICENSES.md).
`make licenses-check` проверяет оба Python окружения и npm, без сетевых запросов.
Повтор сбора: `tgbot/.venv/bin/python scripts/collect_license_metadata.py --project tgbot --wheel-dir /path/to/wheels`,
затем `tgbot/.venv/bin/python scripts/licenses_check.py --project tgbot --write`.
Wheel fallback проверяет SHA256 в соответствующем lock; версия из другого
окружения не принимается за доказательство. CI устанавливает bot через
`uv sync --frozen` и запускает его lint/types/fake tests отдельно.
T-041: добавлены LangGraph1.2.19 и langgraph-checkpoint-postgres3.2.0 (MIT) по ADR0003. Вместе с транзитивными/platform dependencies inventory содержит548записей (111Python+437npm). Upstream PostgreSQL DDL3.2.0 перенесён в0012 с полным MIT notice; runtime setup/DDL не выполняется. jsonpointer3.7 notice проверен как BSD-3-Clause с version-bound hash; distro/requests-toolbelt Apache notices проверены. Platform-only wheels colorama/httpx2-jsfetch/tzdata проверены по uv.lock SHA256 без установки. Gate не ослаблен.

T-051, объединение базы T-048/T-041: inventory пересобран в отдельном uv-окружении; 550 записей (113 Python + 437 npm). OpenAI SDK и LangGraph сохранены вместе, версии существующего T-041 lock не обновлялись. Platform-only httpx2-jsfetch 1.0 проверен по SHA256 wheel из lock; установка в canonical venv не выполнялась.
