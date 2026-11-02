# T-244: композиция с main 7e34ffb

Обычный merge main `7e34ffbd33b9eaaf6dfe5f75953464d9ed118a43` дал `a065fa4841bfa57f4cb1501201093e01a7a6f3e9`. Report producer, shared SQL, templates, frontend, OpenAPI и report tests byte-identical подготовленному `b971710fdc428ec98d217cc0aa765ebb39769703`. Единственный конфликт privacy tests разрешён сохранением обеих групп: reviews и CSI.

На composed source: `make lint` EXIT0, 421 frontend tests / 59 files, Ruff backend 463 files, mypy 295; bot 11/5; OpenAPI drift 193/193. Собственная PostgreSQL 16 БД: 10 integration tests passed за 151.46 с — cabinet cold signals, report p95 с первым GET, Trace fanout, bounded projection, journey acceptance. Порог производительности не изменён.

После этого test-only `44f5070` переносит fixture assertions с literal 0018 на точную Alembic head. Production source не меняется; чужая ancestry prevention runtime не переносилась. Полный exact-head CI ещё обязателен. Исторические source-specific результаты сохранены в исходных proof artifacts и не объявляются новым полным прогоном.

Нет реальных LLM/Telegram/email вызовов и изменений рабочей БД. Карточка остаётся in_progress до CI и review API1.5.26. Зависимость PR — T-242; foundation/API25/27/28 не поглощаются неявно.
