# T-240: граница истории и площадок после P1

Основа: ordinary merge P1 `727d1db` (actual Alembic `0013`, OpenAPI `1.5.18`).
Миграция `0014_product_history_scope` сохраняет все legacy строки без угадывания
запуска, sentiment quality или интервала. NULL owner читается только явным
`scope='all'`; новые INSERT/UPDATE требуют положительный существующий run_id,
согласованные счётчики и непустой интервал внутри календарного месяца MSK.
Прежний global UNIQUE определяется по metadata колонок, включая иной порядок
и operator-defined имя; новый ключ — `(run_id,product_line_code,month)`.
FK имеет ON DELETE CASCADE. Повтор SQL не меняет данные.

`sentiment_known_count=NULL` у legacy означает неизвестное качество. Смешанный
итог не превращает legacy в neutral: known/negative/unknown возвращаются NULL.
Синтетическая история не выводит потери из количества жалоб: `loss_rub=NULL`.
Существующие legacy суммы не переписываются и не выдаются за наблюдённые потери.
Данных о реальных финансовых эффектах эта карточка не создаёт.

Pure builder принимает только типизированный optional Sentiment. Последние
14 дней группируются по фактическим line/source/severity без достройки месяца;
unknown sentiment учитывается отдельно. На точной границе первого дня месяца
последний bucket — предыдущий месяц: будущая синтетика не создаётся.

CLI `--apply` держит существующий shared maintenance lease до commit. Failed
marker или exclusive restore отклоняет импорт до эффектов; dry-run БД не читает.

OpenAPI `1.5.19` добавляет optional Signal.source_platform: только известные
code/name_ru/name_en/type из data/platforms.yaml; неизвестный meta-код → null.
Произвольные source_url/meta/gold не публикуются. Это forward contract; UI до
собственной проверки не считается готовым.

## Проверка и восстановление

Реальные PG16 tests отдельно проверяют сохранение legacy, повтор миграции,
изоляцию двух запусков, запрет NULL/foreign owner/невалидных counts/coverage и
CASCADE. Namespace теста имеет уникальное имя и откатывается внешней транзакцией;
исходная fixture не удаляется. Fixtures создают sim_runs штатным helper, перед
CASCADE освобождается его current pointer — это не изменение runtime lifecycle.

Откат приложения сохраняет аддитивные поля; downgrade не стирает ownership.
Возвращать старый global UNIQUE при нескольких запусках нельзя. Для полного
восстановления использовать проверенный backup в остановленном стенде по
существующей baseline maintenance процедуре; автоматического rewrite legacy нет.

Это промежуточная граница, **не завершение T-240**: фактический seed корпуса и
180 channel cells, persist/history tail, новый baseline dump и полный regression
ещё обязательны. Production и внешние LLM вызовы не выполнялись.

Checkpoint verification: 44 pure tests passed; 7 import/maintenance/API PG tests
passed; standalone legacy/reapply/FK/CASCADE PG test passed (7.14 s). Changed
backend Ruff/mypy green; contracts_check:45 schemas/162 paths; actual PG16
`alembic check`: No new upgrade operations detected. Полный regression на этом
checkpoint ещё не запускался; прежние independent proof не расширяются автоматически.

## Следующий seed checkpoint

Actual seed теперь добавляет 162 canonical reviews и 151 недостающий channel
instance; date mapping только seed: исходный source_date сохраняется, экземпляр
сдвигается относительно immutable reference_anchor, offset явно записан.
Исходные 800 T019 signals не меняются. Для их прежнего noise denominator и
общей hard доли добавлены 48 настоящих hard templates и 1 настоящий noise.
На lite/200 fixture итог1162, hard_share>=25%, generated noise ровно3%.
Все180 direction×channel и прежние480 type×product×channel cells покрыты.

История180 rows; mapped tail313 совпадает с actual по каждой line/source/severity
ячейке (0% отклонение). Unmapped849 записан явно: неоднозначный старый cohort
не получает направление по догадке. Новые editorial rows имеют status classified,
не фиктивный ответ/AR и не очередь runtime агента. CSI15 связано с существующими
branch FK; voice/branch channels — только синтетический текст, не STT/audio.
Фактических fault→physical-line связей у старого cohort нет: пустое множество
spike months не выдаётся за наблюдённую каузальность. Pure spike-механика ранее
проверена отдельно; actual источник остаётся явно ограниченным.

Повтор stage проверяет corpus SHA/seed/canonical UTC anchor и сохраняет rows/IDs;
другой корпус требует явного rebuild. Injected save failure откатывает все
новые signals и receipt; затем retry проходит. 3 actual PG tests passed23.71s
(включая исходный T019 test без ослабления assertions). Новый stage/adapter/coverage
mypy green; сквозная проверка scripts/seed/run.py отдельно выявляет уже существующий
fetchone()[0] typing warning вне изменённых строк. Полный make lint/test ещё впереди.

Композиция actual schema9/currenthash кассеты и main2ed сохранена ordinary merges;
P1 explicit replay/Pro role pinning и maintenance fixture сохранены. Совместный
stream limiter+bound-provider код сверён с P1 reference43af7af, без обхода RPM.
34 strict replay/currenthash/miss/limiter targeted tests passed15.42s.

UI source: SourcePlatformBadge в SignalsFeed/SignalDrawer; ru/en известные имена,
unknown/legacy не выдумывает placeholder, нет href/URL/img. Пять новых UI tests,
включая фактический click→open карточки. Полный make lint exit0:225 frontend tests,
Ruff413files/mypy275modules, OpenAPI192/192; licenses550 green. Выполнен штатный
make sync-contracts с own scratch DB; canonical0013 downgrade comment согласован
с существующим forward-only mirror, исполняемый SQL не менялся.
Четыре browser language/theme screenshots и полный make test ещё обязательны.
