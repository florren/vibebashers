# T-161: итоговая граница runtime, событий и миграции 0017

Уже согласованы численные значения demo-policy и вариант A: отдельная вероятность
churn intent за 15 минут в `client_states`, прежний `clients.churn_risk` сохранён.
Эти решения не повторяются как новый запрос. Конкретный кандидат включает следующие
дополнительные изменения, требующие финального human review по AGENTS.md §5.1/§7.

1. Миграция 0017 добавляет durable behavior state, pending work, receipts, evidence
   и привязки к своему run. Candidate включает policy (`enabled: true`), только для
   `free`/`scenario`; `live` не получает hazard. Пустой совместимый run получает marker,
   непустой legacy run без доказательств модели отклоняется до эффектов и требует
   явного нового run с сохранением истории. Чужие current clock и RNG не заимствуются.
2. `reset_day` при включённой модели проходит обычные Sim ticks до 09:00 следующего
   календарного дня, сохраняя pending work и порядок фактических событий. Это изменение
   прежнего скачка часов. Вероятности, рабочий календарь и финансовые лимиты сохранены.
3. После ожидания LLM инструменты получают native persisted время своего run перед
   эффектом. Это касается также timestamps уведомлений, SLA/tasks и Mock-АБС ledger.
   Complaint happened time остаётся исходным; повтор idempotent эффекта не меняет
   существующую запись. Суммы, формулы, rules и HITL не меняются. Подробности:
   `T-161-effect-time-financial-review.md`.
4. Восстановление активных faults читает сохранённые duration/correlation и реальные
   операции без RNG/записей. `fault.regression` получает optional
   `expected_duration_min`. Неоднозначные активные legacy/manual события дают явный
   отказ вместо выдуманных 90 минут. Подробности: `T-161-native-fault-recovery.md`.

## Проверки

Пакет зафиксирован на `280c8e7` поверх прямого P2 parent `25852b8`.
На runtime `70e4b00`: 1725 unit passed /18 skipped; отдельный actual-PG/package
набор 167 passed; покрытие 1657/1772 statements (93,51%), каждый из 11 behavior
модулей не ниже 90,12%. После композиции 11 runtime SHA совпадают:
46 T235 tests и 55 owner/effect-time/Twin/inactive/fault/atomicity tests прошли.
`make lint` успешен: 366 frontend tests, Ruff472, mypy297, drift192/192;
contracts45/162, licenses550+36. Source-qualified proof:
`T-161-parent-composition-proof.json`.

Прежний полный integration на `9bba1d9` дал 469 passed /2 failed /4 skipped.
Две причины исправлены в `70e4b00`, проверены адресно; этот старый прогон
не объявляется зелёным. Полный CI нового PR обязателен до merge. Whole-World
recovery до первого team action требует отдельного T-037 durable-plan PR;
данный пакет не закрывает этот пробел и не объявляет всю T-161 завершённой.

## Rollout и откат

Рабочая БД и внешние сервисы не изменялись. Перед rollout/rollback остановить
simulation actors штатным control API и сохранить резервную копию. Применять 0017
после 0016; сначала проверить миграцию на копии. Отключение policy не является
разрешением продолжать старый run с другой моделью: сохранить его историю и явно
создать совместимый новый run. Сохранённые события и evidence не удалять;
не исправлять неизвестные active faults эвристическими timestamps. Откат кода
выполняется на остановленном стенде, с сохранением additive таблиц и событий;
DDL downgrade требует отдельного решения и этим PR не разрешается.
