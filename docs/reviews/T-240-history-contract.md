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
