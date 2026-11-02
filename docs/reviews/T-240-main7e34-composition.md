# T-240: композиция с обновлённым P1/main

Обычный merge parent199290f (P1 плюс main7e34ffb) в c99ee5b дал4d583bfa. Единственный add/add конфликт test_no_pii.py разрешён сохранением обеих исходных групп assertions: review corpus и CSI corpus; никакие privacy проверки не удалены. API1.5.19/DDL0014 и утверждённая semantics T-240 не менялись.

На composed source `make lint` EXIT0:359 frontend tests/45files, Ruff426, mypy276, OpenAPI192/192.47 unit/actualPG tests за61.44с на собственной cx_t240_corpus_revision: оба privacy tests, review/CSI pure corpus, product-review seed, product history scope и native review import. PostgreSQL16 tooling/оба scratch URL/ENV_FILE=/dev/null. Новых внешних вызовов и рабочей БД нет.

Два gen_tasks запуска без изменений tracked files. После push обязателен exact-head CI; прежний зелёный CI не переносится на обновлённый head. Human API/DDL review PR183 уже получен; merge возможен после parent180 и зелёного финального CI.
