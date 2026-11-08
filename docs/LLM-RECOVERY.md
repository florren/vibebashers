# Восстановление штатных LLM после unknown usage

Для GigaChat с уже созданным application origin локальный `usage_known=false`
не отключает дальнейшую работу: перед каждым новым physical inference проверяется
свежий `/balance` именно выбранной модели. Положительный пакет разрешает новый
вызов; ошибка/нулевой остаток не разрешают его и могут переключить пул на второй
ключ. Unknown attempts и подтверждённые counters сохраняются, история не
объявляется нулевой. Для этих credentials §3–4 нужны только для уточнения
истории; повторное подключение или новый ключ для продолжения работы не нужны.

При unknown локальный token cap применяется к подтверждённому расходу и не
доказывает точный верхний предел; `tokens_remaining` остаётся неизвестным.
Остаток пакета у провайдера и локальный счётчик расхода — разные показатели.
OpenRouter и legacy credentials без GigaChat origin сохраняют прежние ограничения.

Для проверки используйте новые agent runs после возобновления: `model` шагов
должен содержать `gigachat:...`, `status=ok`; старые fallback/HITL не исчезают.
Проверьте движение `sim_time` и ответ Pause/Resume при работающем demo-операторе.
Оператор фиксирует HITL под lock часов, а продолжает граф уже вне него.

OAuth, `/models` и успешный отдельный diagnostic smoke не доказывают готовность
штатного inference. Если operational ledger сообщает `usage_known=false` или
незавершённую попытку, GigaChat/OpenRouter могут быть доступны по сети, но новый
бюджетируемый вызов без API-backed GigaChat origin будет отклонён до HTTP. Перезапуск, банковский seed/restore
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

## 2. Подключить неиспользованный резерв GigaChat без Studio

Для ключа без предыдущих application attempts и legacy token floors используйте:

```bash
python -m app.llm.accounting_cli connect-gigachat \
  --profile-id PROFILE_ID --env-slot gigachat2 --confirm
```

CLI выполняет OAuth и `GET /balance`, без inference и без браузера. Он создаёт
один приватный origin с `historical_usage_known=false`. С этого момента
`tokens_used` — **расход приложения с подключения**, а не история проекта.
Настроенный token cap действует для этого app-scoped расхода; численные limits
не изменяются. Предыдущее unknown сохраняется в audit, не объявляется нулём.
Общий суточный счётчик профиля и существующие floors не уменьшаются.

Повторная команда не создаёт новый бюджет и не снимает unknown после HTTP.
Ключ с предыдущими attempts/legacy расходом должен пройти обычный reviewed
reconciliation (§4); произвольно начать учёт заново нельзя. Подключённые таким
способом ключи перед каждым structured/stream inference дополнительно проверяют
пакет выбранной модели через `GET /balance`. Отсутствие/ошибка/исчерпание пакета
не резервирует inference; structured pool пробует другой ключ. Успешный `usage`
сохраняется в PostgreSQL как раньше; отсутствие usage блокирует следующие calls.

Pay-as-you-go может возвращать403 на `/balance`; этот способ подключения для
него не подходит. Не суммируйте пакеты разных моделей: их остатки независимы.
Открытые вкладки, аккаунт Studio и пароль для этого пути не требуются.

## 3. Сверить существующий неопределённый расход

1. Сохраните приватную резервную копию `llm_runtime` штатным `pg_dump` версии
   сервера. Банковский baseline не содержит operational ledger. Не добавляйте
   dump, `.env`, credentials или экспорт кабинета провайдера в Git.
2. Сопоставьте credential с точным проектом/ключом провайдера. Для существующей legacy-сверки GigaChat нужна проверенная
   operator observation, согласованная с app ledger; ни CLI, ни runtime не
   обращаются к Studio. GET /balance не восстанавливает историю. Для OpenRouter фильтруйте activity по точному ключу: другие ключи
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
Не обращайтесь к Studio как к runtime dependency. Сохранённые app attempts и
подтверждённые operator observations — источники для reconciliation. При новом
неиспользованном резерве применяется §2: прошлый расход не требуется и остаётся
unknown. Разрешение восстановить сервис не доказывает нулевой прошлый расход.

## 4. Выполнить существующий reconciliation

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

## 5. Проверить обычный consumer

В `/setup`, шаг **LLM**, у нужного профиля нажмите **Проверить**. Используется
обычный `/api/setup/test-llm` и durable accounting, а не исключение standalone
diagnostic CLI. Проверка передаёт только фиксированный ping и JSON schema;
реальные внешние вызовы выполняйте только при разрешённой передаче/расходах.

Сверьте live success, сохранённый usage, увеличение ledger и отсутствие
неподтверждённых новых attempts. При сетевой неопределённости unknown сохраняется;
для API-backed GigaChat доступность следующего вызова проверяется по свежему
остатку пакета. Нельзя повторять попытки через ручной сброс unknown.

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

## Linux: хост видит GigaChat, backend bridge не видит

Сравните доступ к OAuth и API именно из рабочего backend. Успешная сборка с
`BUILD_NETWORK=host` не проверяет runtime. Например, VPN/TUN может перенаправлять
исходящие соединения Docker на локальный proxy, недоступный из bridge-сети.
Не отключайте TLS, VPN или firewall ради диагностики.

Для такого Linux-стенда есть opt-in конфигурация проекта:

```dotenv
COMPOSE_FILE=docker-compose.yml:docker-compose.host.yml
```

Добавьте эту строку в локальный `.env`, затем примените существующий образ:

```bash
docker compose config --quiet
docker compose up -d --no-deps --no-build backend
```

Backend использует host network и PostgreSQL на `127.0.0.1:5432`; порт API
остаётся 8000. PostgreSQL и personal остаются в обычной сети. Опциональный
Mailpit доступен backend по опубликованному SMTP-порту `127.0.0.1:1025`, а не
по Docker DNS-имени `mailpit`. Telegram service,
если он включён, тоже использует host network и backend `127.0.0.1:8000`;
пересоздайте его через `docker compose --profile telegram up -d --no-deps --no-build tgbot`.
Режим предназначен для Linux Docker Engine с поддержкой Compose `!reset`.
Backend разделяет сетевой namespace хоста; это явный выбор окружения, а не
смена дефолта для CI/других установок. Изменения системных firewall-правил,
повышенные privileges, новый proxy и отключение проверки сертификатов не нужны.

`--restart` перезапускает уже существующие контейнеры; для смены network mode
нужен именно `up` выше. Проверка занятых портов при обычной установке/`--reset`
поддерживает host mode: listener должен принадлежать процессу своего контейнера
с private PID namespace, а не просто существовать на хосте. Базовая bridge
конфигурация продолжает проверяться через published ports.

После смены сети проверьте «Проверить подключение» для выбранного LLM-профиля
и статус accounting из §1. Доступные OAuth/баланс не снимают unknown usage.
Unknown у GigaChat с application origin больше не блокирует новый вызов,
если проверен положительный пакет выбранной модели. При старом образе эта
логика ещё не действует: необходима сборка и пересоздание backend.
Для свежего ключа без application attempts и legacy floors используется §2;
для существующего неопределённого расхода — §3–4. Не считайте mock ответом GigaChat.

Откат сети: удалите `COMPOSE_FILE` из локального `.env` и пересоздайте backend
(и используемый tgbot) с базовым `docker-compose.yml`. Данные и учёт расхода
не сбрасывайте. Смена сети не исправит первопричину блокировки bridge на хосте,
поэтому перед откатом убедитесь, что исходный маршрут снова доступен.
