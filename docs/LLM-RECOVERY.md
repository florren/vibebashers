# Восстановление штатных LLM после unknown usage

OAuth, `/models` и успешный отдельный diagnostic smoke не доказывают готовность
штатного inference. Если operational ledger сообщает `usage_known=false` или
незавершённую попытку, GigaChat/OpenRouter могут быть доступны по сети, но новый
бюджетируемый вызов будет отклонён до HTTP. Перезапуск, банковский seed/restore
и смена названия профиля не восстанавливают allowance.

## 1. Проверить выбранный источник

В работающем backend используйте существующий CLI:

```bash
python -m app.llm.accounting_cli status --profile-id PROFILE_ID --env-slot gigachat2
```

`PROFILE_ID` — текущий ID из `/api/settings/llm-profiles`, не ID AgentRun.
Для OpenRouter source — `--env-slot openrouter`; для основного GigaChat —
`gigachat1`. Если профиль привязан к registry credential, вместо env slot нужен
`--key-id KEY_ID`. CLI не принимает raw credentials в argv.

Проверяйте `admission_allowed`, `usage_known/source/as_of`, `requests_day`,
`requests_known`, остатки ключа и общий остаток профиля. Нулевой `tokens_used`
при `usage_known=false` не является подтверждённым нулевым расходом.

## 2. Собрать наблюдение, не изменяя policy

1. Сохраните приватную резервную копию `llm_runtime` штатным `pg_dump` версии
   сервера. Банковский baseline не содержит operational ledger. Не добавляйте
   dump, `.env`, credentials или экспорт кабинета провайдера в Git.
2. Сопоставьте credential с точным проектом/ключом провайдера. Для GigaChat
   используйте статистику API выбранного Studio-проекта за весь период его
   работы. Для OpenRouter фильтруйте activity по точному ключу: другие ключи
   аккаунта могут иметь отдельную историю. Сохраните источник, период,
   результаты и время наблюдения приватно.
3. `/balance` GigaChat показывает остатки по моделям, `/key` OpenRouter —
   денежный расход и отдельный free request counter. Остаток или USD не равны
   использованным токенам. Не вычисляйте прошлый расход из предполагаемого
   стартового пакета и не переносите статистику одного проекта на другой.
4. Счётчики запросов сверяйте за **текущие UTC-сутки**. UI кабинета может
   показывать другой часовой пояс. Суточный счётчик профиля общий для его
   ключей: ноль запросов нового ключа не обнуляет уже потраченный profile cap.
5. Наблюдение должно быть актуальнее всех attempts. Значения не могут быть
   ниже уже подтверждённых token/request floors. Даже доказанная локальная
   ошибка сериализации после admission не даёт уменьшить счётчик attempts.
   Для unknown после сетевого сбоя требуется отдельная сверка провайдера;
   отсутствие ответа не доказывает отсутствие расхода.

Если источник неполон или расход не удаётся установить, сохраните unknown.
Сначала получите данные недостающего проекта; разрешение восстановить сервис
не является доказательством нулевого прошлого расхода.

## 3. Выполнить существующий reconciliation

После проверки замените все метки реальными подтверждёнными значениями:

```bash
python -m app.llm.accounting_cli reconcile \
  --profile-id PROFILE_ID --env-slot gigachat2 \
  --reconciliation-id UUID --as-of ISO8601_WITH_TIMEZONE \
  --tokens-used TOKENS_USED --requests-today KEY_REQUESTS_TODAY \
  --profile-requests-today PROFILE_REQUESTS_TODAY \
  --confirm --reviewed-unknown-origin
```

`as_of` должен относиться к текущим UTC-суткам и не быть будущим. UUID сохраняют
для идемпотентного повторения **того же** observation. CLI сохраняет audit,
прежний source, legacy hints и связанные attempts. Не правьте таблицы вручную
и не уменьшайте лимиты/счётчики для обхода отказа. `--acknowledge-orphans`
нужен только после явной проверки expired reserved attempts; он не разрешает
скрытую повторную отправку HTTP.

Повторите `status`. Для каждого используемого ключа должен быть подтверждён
собственный расход; разблокировка одного ключа не разблокирует остальные.

## 4. Проверить обычный consumer

В `/setup`, шаг **LLM**, у нужного профиля нажмите **Проверить**. Используется
обычный `/api/setup/test-llm` и durable accounting, а не исключение standalone
diagnostic CLI. Проверка передаёт только фиксированный ping и JSON schema;
реальные внешние вызовы выполняйте только при разрешённой передаче/расходах.

Сверьте live success, сохранённый usage, увеличение ledger и отсутствие
неподтверждённых новых attempts. При сетевой неопределённости снова потребуется
сверка; нельзя повторять попытки через ручной сброс unknown.

При отдельном Python-проверяющем коде загружайте профиль штатным loader:
`app.llm.roles.select` приводит SQL numeric к `float`. Прямой `LLMProfile(**row)`
не делает такого преобразования; `Decimal` в request body может оборвать JSON
сериализацию уже после durable admission. Это не успешный live-вызов.

## Воспроизводимая offline-проверка

`backend/tests/integration/test_llm_recovery_protocol.py` соединяет настоящие
GigaChat/OpenAI-compatible provider classes с PostgreSQL accounting и
`httpx.MockTransport`. Проверяет preflight без HTTP, подтверждённое восстановление,
committed reservation до transport, типы SQL-профиля, сохранение cap после
пересоздания provider и отказ после отсутствующего usage. Credentials и ответы
в тестах синтетические; реальных внешних вызовов нет.

## Recovery

При сбое не удаляйте ledger и audit, не восстанавливайте старый dump поверх
новых расходов. Сохраните состояние, остановите дальнейшие budgeted вызовы и
проведите новую reviewed reconciliation. Численные caps, цены и банковские
правила этой процедурой не меняются.
