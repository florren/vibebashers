# Лицензии сторонних компонентов

| Компонент | Лицензия | Источник / путь в репозитории |
|---|---|---|
| Inter | SIL Open Font License 1.1 | https://github.com/rsms/inter — бинарники `frontend/public/fonts/inter-*.woff2`, notice `frontend/public/fonts/Inter-OFL.txt` |
| JetBrains Mono | SIL Open Font License 1.1 | https://github.com/JetBrains/JetBrainsMono — `frontend/public/fonts/jetbrains-mono-*.woff2`, notice `frontend/public/fonts/JetBrainsMono-OFL.txt` |

Шрифты поставляются локально (без CDN и без npm `@fontsource/*`), см. `data/README.md` и карточку T-263.

### CSI import (T-246)

- openpyxl 3.1.5 — MIT, [PyPI / upstream](https://pypi.org/project/openpyxl/); чтение XLSX read-only.
- et-xmlfile 2.0.0 — MIT, [upstream](https://pypi.org/project/et-xmlfile/); зависимость openpyxl.
- defusedxml 0.7.1 — PSF License, [upstream](https://pypi.org/project/defusedxml/); защита XML при чтении пользовательских XLSX (рекомендация upstream openpyxl).

### Публичные сертификаты GigaChat

`backend/app/llm/certs/` содержит общедоступные X.509 сертификаты НУЦ Минцифры с gu-st.ru и их объединение `gigachat-ca.pem`. Это публичные сертификаты, не закрытые ключи и не новые программные зависимости. Источники, SHA-256 fingerprints и даты действия — в README каталога. Системное хранилище доверия и certifi не модифицируются; цепочка добавляется только в SSLContext клиента GigaChat.

### Инструменты baseline (T-270)

postgresql-client-16 (pg_dump, pg_restore, libpq) — PostgreSQL License, [официальная лицензия](https://www.postgresql.org/about/licence/). Устанавливается в Docker через подписанный [официальный PGDG](https://www.postgresql.org/download/linux/debian/), Debian bookworm; версия сервера остаётся 16. Python/npm-зависимости не добавлялись.
