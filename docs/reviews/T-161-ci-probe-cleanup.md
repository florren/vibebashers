# T-161: изоляция lifecycle fixture после полного CI

Полный CI head `d0867fc` завершился: backend shards0/1/2 успешны; shard3
дал 659 passed и 7 failures. Первая причина — таблица `lifecycle_composite_probe`,
созданная тестом внешнего composite FK и не удалённая после него.
Strict schema count видел94 вместо93, Alembic check предлагал удалить probe;
последующие downgrade-тесты каскадно оставались на неполной схеме.

На собственной PostgreSQL fixture повтор того же порядка
lifecycle external → schema воспроизвёл94!=93:1passed/1failed,7,30с.
Исправление `71f639f` касается только test_run_lifecycle.py: созданный этим тестом
probe удаляется в finally, затем явно проверяется его отсутствие.
Это тот же cleanup, который уже проверен в составе T-241 (`f987`).
Schema count, Alembic drift, downgrade guards и production DDL не меняются.

После исправления полный lifecycle → schema: **23 passed,83,47с**, включая
строгие count/drift/downgrade проверки. Ruff/format/diff-check прошли;
все11 behavior runtime SHA прежние. Численные policy, runtime activation и
остальная ранее утверждённая граница PR193 не изменяются.
Повторный exact-head CI обязателен; старые7failures не объявляются зелёными.
