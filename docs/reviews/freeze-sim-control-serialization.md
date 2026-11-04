# Freeze: сериализация Simulator.control и native tick

## Дефект

У одного Simulator методы control и tick используют одно psycopg-соединение.
Общий control preflight читал sim_state и сравнивал memory time/RNG до захвата
Python lock. Tick в это время мог уже изменить RNG/часы и записать native операции
в ещё незавершённую транзакцию. Control видел промежуточное состояние как stale,
возвращал409 и вызывал rollback на соединении активного tick.

На отдельном native стенде это проявлялось как непостоянный409
`Simulator устарел: загрузите актуальные time/run/RNG перед управлением`
при обычном запуске следующего сценария в том же процессе.

Аналогичные shared-connection окна были у чтения effective_policy в reset_day
и между завершающим persist/commit после ручного step/jump/reset_day.

## Изменение

- Общий control preflight, включая SELECT и возможный rollback, выполняется под
  тем же self._lock, который защищает tick.
- reset_day читает policy и рассчитывает target под этим lock.
- Завершающий control persist/commit остаётся под lock до конца транзакции.

Существующие row locks и проверки настоящего stale run/time/RNG/status сохранены.
Python lock не удерживается через self.step, _stop_loop и resume hooks;
порядок Python lock → PostgreSQL row lock остаётся прежним.
Новых retries, sleeps или ослабленных guards нет.

API, DDL, события, размеры шага, формулы, ставки, лимиты и HITL не меняются.
Старые данные и failed/прерванные запуски автоматически не исправляются.

## Проверки

Детерминированная PG16 регрессия создаёт настоящие World operations/RNG, затем
останавливает tick после продвижения memory-clock до первого persist.
Control обязан дождаться tick, затем сохранить прежние native факты и актуальные
часы. Отмена ожидающего control не откатывает чужой tick.

Дополнительные расписания блокируют настоящий post-step UPDATE до commit и
чтение reset_day policy; следующий tick обязан ждать владельца соединения.
Синхронизация событийная, без sleep-гонок и случайных повторов.

- RED на исходном engine: пять failed, 30.87s.
- GREEN: пять passed, 32.55s.
- Расширенная composition: 72 passed, 417.44s. Проверены настоящие stale
  time/RNG/status отказы, ручные controls, behavior, Team/RNG recovery,
  maintenance/OS crash и lock ordering. Вместе с пятью новыми cases:77 plain PG passed.
- Отдельный instrumented прогон:5 passed, 33.27s. Stdlib sys.settrace
  выполнил18/20 bytecode-executable AST statement starts добавленного diff (90%).
  Raw AST консервативно18/21 (85.71%); строка474 — многострочный If header
  без bytecode line в Python3.12, поэтому не входит в executable denominator.
  Это не branch coverage и не заявление о полном покрытии проекта.
- Source и тесты Ruff check/format passed; mypy engine: no issues.

Все тесты выполняются только на собственных PostgreSQL16, LLM mock;
primary БД, operational ledger и внешний API не затрагиваются.

## Review и откат

Изменение защищает общую транзакцию native tick, включая операции/экономические
факты. Поэтому финальная граница требует human review по AGENTS.md §5.1:
«всё, что касается денег и HITL», хотя расчёты и денежные правила не меняются.

Откат — вернуть прежний engine после остановки тестового runtime. Сохранённая
история не переписывается; откат возвращает риск конкурентного rollback/409.
Production rollout и починка прежних запусков этим тестом не выполнялись.
