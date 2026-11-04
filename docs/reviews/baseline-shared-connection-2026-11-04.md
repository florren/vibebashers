# Baseline: владелец общей транзакции Simulator

На f297480 подтверждён дефект `POST /api/sim/baseline`: проверка отсутствия
активного запуска завершалась до получения общего `Simulator.conn` без
`sim._lock`. `baseline.dump()` первым действием выполняет `conn.commit()`,
чтобы открыть собственную READ ONLY REPEATABLE READ snapshot. Он мог
зафиксировать ещё не завершённую native-транзакцию другого control.

## Доказательство

Только собственная свежая PostgreSQL 16, Mock, без внешних ключей/запросов,
артефакты dump в `tmp_path`. Event barrier остановил настоящий `control start`
после SQL `create_run`, до присвоения Python state и штатного commit.
Транзакция имела `INTRANS`; отдельное подключение видело 0 новых запусков.
После параллельного baseline API оно увидело 1 запуск, хотя control оставался
заблокированным. Это premature commit, а не предположение по исходному коду.
Dump остановлен следующим event barrier до публикации архива.

Четыре durable PG/API-регрессии на исходном f297480: **4 failed, 8,13 с**.
Обе очередности используют настоящие HTTP routes и MaintenanceMiddleware:

- control владеет незакоммиченной TX → baseline обязан дождаться; cancellation
  ожидающего baseline не затрагивает TX control;
- настоящий `pg_dump` владеет exported snapshot → новый control обязан дождаться;
  cancellation baseline не освобождает conn до завершения supervised exporter.

## Изменение

Handler baseline сохраняет быстрый исходный guard, затем получает `sim._lock`
и повторно проверяет отсутствие активного запуска. Lock удерживается через
`connect`, весь `dump` и завершающий `commit`. Если ожидавший control уже
запустил банк, возвращается прежний HTTP409 для активного запуска. Свободный
неактивный банк по-прежнему получает HTTP202 и настоящий архив/checksum/meta.

Guard, schema/LLM fingerprint, формат архивов, initial commit в dump, формулы,
суммы, лимиты и HITL не менялись. Нового глобального exclusive gate нет:
сериализуются пользователи одного `Simulator.conn`.

Подтверждена граница native control TX, а не реальная финансовая выплата.
Поскольку это соединение используется для native эффектов симуляции,
финальный review относится к атомарности транзакции; он не утверждает
изменения финансовых правил или разрешение пересоздать рабочий baseline.

## Проверки

После изменения: **24 passed, 56,81 с**, включая новые PG/API/cancellation,
existing baseline unit/actual restore и control/tick serialization.
Existing unit fixture теперь задаёт настоящий `asyncio.Lock`: приватный
`MagicMock._lock` является внутренним `threading.RLock`, непригодным для
имитации интерфейса Simulator. Assertions не ослаблялись.

Ruff check и format изменённых Python-файлов прошли; mypy `app/api/sim.py`
прошёл. Покрытие всех изменённых executable строк единственного backend
producer: **8/8 = 100%**, без missing строк; [машинное доказательство](baseline-shared-connection-coverage.json).
Это не процент покрытия всего проекта. Общий CI нового PR должен пройти
отдельно; полный immutable прогон f297480 не является прогоном этого diff.

## Применение и откат

Миграций и пересоздания данных не требуется. Исправление не переписывает
существующие архивы/историю. Revert возвращает прежний handler и подтверждённую
гонку; до повторного исправления создание baseline допустимо только на
остановленном собственном стенде без конкурентного control/tick.
Пользовательский baseline/БД в этих проверках не изменялись.
