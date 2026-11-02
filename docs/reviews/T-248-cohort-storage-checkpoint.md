# T-248: локальный CSI cohort storage checkpoint

Это кандидат реализации, не финальная API/DDL приёмка. API28 ещё не подключён;
существующий CSI endpoint остаётся501. Migration0020 временно опирается на0018
только в собственной fixture. Перед PR обязателен clean0019 parent и actual
upgrade19→20. Рабочие БД, внешние LLM и Telegram не использовались.

Три additive таблицы сохраняют run/branch/declared direction/window, source и
directory digests, membership и visits. Legacy csi_visits_agg не переписывается.
Composite FK запрещают чужие run/branch ссылки, timestamp проверяется внутри
[start,end), snapshot строки не редактируются. FK lifecycle deletion разрешён;
SQL/Python digest reader отличает удалённые строки от полного snapshot.
Integrity view использует встроенный PostgreSQL16 sha256, один MVCC snapshot и
индексы по cohort_id. Данные участников целиком не передаются приложению.

Отдельный csi_scoped_v2 явно задаёт synthetic direction из обслуживаемого
каталога. Это sample declaration, не классификация агента: signals.product_line_code
и LLM outcomes не заполняются. Исходный csi_v1 не изменён. Окно — предыдущий
день seed; native clock не переводится назад. response_at — источник observation,
received_sim — native ingest time. Перемешивать эти временные оси для rate нельзя.

Регистрация работает внутри caller TX, требует текущий небазовый run и
остановленные часы, известный synthetic directory/roster и завершённое окно.
Все300 сигналов идут через штатный normalizer. Проверяются принятые payloads,
run, branch, employee и actual CSI details. Точный повтор идемпотентен;
чужие/изменённые/частичные данные не переназначаются и не ремонтируются.
Для другого synthetic запуска нужен явный свободный id_base (кратный300,
30000..899400); автоматического переписывания внешних CSI IDs нет.

## Проверки по источникам

- Первый storage:3actualPG passed18,31с, собственные native CSI signals.
- Первая регистрация:5actualPG passed34,39с: exact retry, foreign run,
  changed accepted payload, failure после normalizer и сохранение прежних записей.
- После immutable snapshots/digests:15unit/actualPG passed63,99с;
  coverage артефакт относится к этому источнику до SQL-view codec уточнения.
- На последнем SQL-view/UTC6 codec:5actualPG passed34,56с;
  все10кохорт complete, удаление bucket даёт ровно1 incomplete cohort,
  повтор не восстанавливает потерянные данные автоматически.
- Генерация authoritative schema/ORM:113 моделей, frontend types;
  Ruff/mypy новых модулей прошли. Полный final coverage/CI ещё требуется.

Рекомендуемый rollback кода сохраняет additive snapshot таблицы. Явный DDL
downgrade0020 удаляет только новые sample tables/view: перед ним нужен backup;
в рабочей БД он не запускался. Exact upgrade/downgrade/lifecycle/restore и
performance всего API будут проверены после подключения0019 и API28.
