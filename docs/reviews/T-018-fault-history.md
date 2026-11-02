
## Композиция после merge родителей

PR166 и PR165 слиты; PR168 переведён на main. На обычной композиции `5378f09`
(main `8b225d5`, включая согласованный stream limiter) actual PostgreSQL checks
fault history, operation COPY и run-summary JSON/CSV: **23 passed за97,86с**.
Все старые assertions сохранены, включая контролируемые1001CSV rows и изоляцию
запусков. Первый запуск без PG16 tools завершился23 setup errors до test bodies:
host pg_dump18 несовместим с сервером16; повтор использовал `/tmp/cx-demo-pg16`.
Это тестовая scratch БД `cx_t018_export_revision`, рабочие данные не менялись.
