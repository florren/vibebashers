# T-275 — проверка автоматического CSI после restore

30.10.2026. Совместимый старый архив моделируется на PostgreSQL16 текущей схемы:
из свежего lite/200 удалён только CSI, матрица — 440/480. Это не конверсия конкретного
неподдерживаемого файла стенда (он отдельно учтён в T-276/#108 по выбору пользователя).

## Автоматические регрессии

```bash
# Обе переменные должны указывать только на изолированную тестовую БД.
DATABASE_URL="$TEST_DB_URL" DATABASE_URL_TEST="$TEST_DB_URL" make lint test
DATABASE_URL="$TEST_DB_URL" DATABASE_URL_TEST="$TEST_DB_URL" backend/.venv/bin/pytest -q backend/tests/compliance
```

Новые unit/API-тесты проверяют subprocess/JSON, DB в окружении вместо argv, ошибки
протокола/кода возврата, отсутствие старта при отказе, наличие скрипта до изменения
БД и сохранение аутентификации. Интеграции выполняют настоящий pg_dump/pg_restore,
проверяют два восстановления старого архива, дополнительный no-op repair, сохранение
прежних строк/решений/ledger/часов/RNG и байтов файлов. Полный архив проверяется
без новых CSI. Пробел вне CSI даёт ошибку без baseline_restore_finished.
Существующий roundtrip теперь намеренно задаёт неверный глобальный DATABASE_URL:
источник истины — переданное соединение, не Settings.

## HTTP на PostgreSQL16

Image cx-pulse-backend:auto-csi-candidate, отдельная DB cx_auto_csi_275 в собственном
контейнере cx-seed-review-pg, APP_ENV=dev, LLM_PROVIDER=mock/LLM_CHAIN=mock,
порт 127.0.0.1:18803. Архив — отдельный /tmp/cx-auto-baseline, не файл стенда.
Сид lite/200, затем удаление CSI только в этой БД и baseline.dump из её соединения.

Два POST /api/sim/baseline/restore → HTTP202: до 731 сигнал/0 CSI/440 покрытия;
после каждого 771 сигнал/40 уникальных CSI/480 покрытия. Agent_runs=0, running=false,
run_id=1 и sim_time=2026-11-09T06:00:00Z неизменны. RNG сравнен непосредственно в
скрипте до/после каждого restore. SHA256 всех файлов архива совпали.
POST /api/sim/runs {kind:free, reset_mode:baseline} → HTTP200; после pause текущий
run_id=2, CSI по-прежнему 40 и покрытие 480. Новый run стартует после ремонта.
Сжатые результаты без большого внутреннего состояния RNG — auto-csi-restore.json.

SQL проверки на тестовой БД:

```sql
select value->>'signal_combos_covered' from settings where key='coverage';
select count(*),count(distinct csi_no) from csi_responses;
select distinct run_id,origin,status from signals where channel_code='csi_survey';
select current_run_id,running,sim_time,rng_state from sim_state where id=1;
select count(*) from agent_runs;
```

## Обнаруженная ошибка адресации и контроль рабочего стенда

При первичном запуске прежнего roundtrip-теста с одним DATABASE_URL_TEST выяснилось,
что async dump/restore используют глобальный DSN, хотя получают тестовое соединение.
Произошло восстановление снимка текущей БД стенда в сам стенд; данные снимка сохранены,
но строка baseline получила started_at из тестовой БД. Это исправлено: операции
теперь привязаны к соединению, а тест намеренно задаёт нерабочий глобальный адрес.

Единственное фактическое отличие started_at baseline точечно возвращено из свежего
приватного backup; вся строка затем совпала с backup. Generated public_id не менялся.
Digest прежних сигналов, решений, ledger, sim_state/RNG, seed_done, .env и исходных
архивов совпал с контрольным снимком; SIG-088489/INC-000826 остался без решения.
Последующие проверки restore выполняются только на выделенных БД с обеими явными
DB-переменными. Исходный старый файл стенда не изменён и не конвертировался.

## Итог локальных проверок

make lint test: Ruff check/format, mypy 231 файлов, OpenAPI drift 186/186,
контракты 42 схемы/158 путей. Unit 599 passed/17 skipped; integration 138 passed/4
skipped; scenarios 22 passed/2 skipped. Дополнительно compliance: 31 passed.
Итого backend 790 passed/23 skipped. Две font-проверки пропущены локально без
сборки frontend; CI выполняет их после сборки. i18n 1416 ключей, owners --allow-cross,
git diff --check — успешно. UI/контракты не менялись.

31 целевая регрессия под coverage и реальный CLI --apply --json на отдельной БД:
новые исполняемые строки 32/34 = 94.12%. См. auto-csi-coverage.json.
