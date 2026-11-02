# T-161: восстановление native расписания World faults

## Конкретный кандидат для обязательного review

`World.load` больше не назначает активным сбоям выдуманные 90 минут, новый correlation UUID и нулевой impact. Адаптер `fault_recovery.load_faults` читает один MVCC-снимок native `fault.started` / `fault.regression`, восстанавливает явный duration/correlation и подтверждённые операции своего run. Загрузка не пишет SQL и не расходует RNG. Для live действует тот же recovery; исключение live из behavior hazard остаётся отдельной границей.

Новый producer `fault.regression` сохраняет прежнюю длительность 90 минут в optional additive `expected_duration_min` и использует correlation реально записанного события. Числа, вероятности и due times не изменены. JSON Schema и штатно сгенерированная Pydantic-модель изменены; DDL, API и LLM response schemas не затронуты.

Неполный/неоднозначный активный legacy/manual event, отсутствующие собственные current часы, будущий started time и несовпадение native fault/event дают `FaultScheduleError` с public run reference и существующим публичным integer fault_id. История сохраняется, автоматического исправления/закрытия нет. Исторические resolved spans не загружаются и не меняются.

**Техническое разрешение реализовать и проверить этот кандидат получено от root. Пользовательский final event/runtime compatibility review, включая отказ для старых активных legacy/manual faults, ещё необходим. Это не разрешение исправлять рабочую БД.**

## Проверки и пределы

На изолированной synthetic `cx_behavior_revision`:

- Основной PG-набор recovery / behavior / causality / atomicity: 34 passed, 206.87 s (`/tmp/t161-world-fault-recovery.log`).
- Дополнительные настоящая team regression, live, noncurrent и event-family mismatch: 4 passed, 24.13 s (`/tmp/t161-world-final-supplemental.log`). До финальной family-проверки отдельный повтор трёх остальных: 3 passed, 18.60 s.
- Full unit: 1725 passed / 18 skipped, 48.60 s (`/tmp/t161-modern-fault-fullunit.log`); затем добавлена только проверка согласованности event family и её PG regression.
- Bounded OS SIGKILL/restart: 1 passed, 15.03 s (`/tmp/t161-process-modern.log`). Aggregate proof и исходные hashes сохранены в `/tmp/t161-process-modern-evidence`; этот proof выполнен до последней family-проверки.
- Ruff изменённых Python файлов и mypy трёх runtime модулей прошли.

Это не новый успешный полный regression всей композиции. Исторический полный прогон на `df01ed6` с 18 failures сохранён в [отдельном отчёте](T-161-live-scope-followup.md); последующие исправления имеют собственные scoped доказательства.

Отдельный T037 gap: `TeamEmulator.load` сам не расходует RNG, но `_build_plan` при tick расходует его до первого due team_action, а план пока хранится только в RAM. Текущий OS-proof **не доказывает** recovery этого интервала. Нужен отдельный durable plan + RNG commit boundary, без раннего take или изменения due times; этот пакет его не маскирует.

## Rollback и операторская граница

Никакие рабочие данные этим исследованием не изменялись. При rollout/rollback сначала штатно остановить simulation actors/часы; данные и native события сохранить. Additive event schema допускает старые записи без нового поля, поэтому не удалять поле из уже сохранённых новых событий. Не возобновлять старый неизвестный активный fault через возврат к эвристике 90 минут. Оставить run остановленным до согласованного forward исправления либо явно создать новый run существующим API, сохранив прежнюю историю (этот путь проверен). Не удалять faults/events и не менять duration/correlation вручную как обход ошибки. DDL downgrade не требуется.

Перед полным/e2e прогоном этот кандидат фиксируется отдельным source checkpoint. Final human review и full CI выполняются по конкретной конечной композиции, не по этому частичному результату.
