# T-234: bounded JSON projection до обновления statistics

Два независимых CI head выявили p95 раскрытия веера выше300ms:
P2 d99b856 —305.9006ms; QR76c1624 —315.5023ms. Остальные response/privacy/
10001members/page50/8MiB assertions проходили. Порог/числоsamples/первыйGET
не менялись, warmup/retry/skip вperformance gate не добавлены.

На собственной PG16 fixture с last_analyze/last_autoanalyze=NULL exact SQL
делал to_jsonb для10001строки передSort/LIMIT51. EXPLAIN ANALYZE READ ONLY
дал39.686ms; wholeASGI cProfile не показал повторногоcold route compile.
Ранее полученный вручную быстрый0.25ms план послеcatch-upstats не доказывал
скорость первоначальногоAPIзапроса. Это воспроизведённая лишняя работа; точный
cloudrunner не воспроизводился и случайнымfailure не объявляется.

Исправление: materialized CTE выбирает максимумlimit+1 идентификаторов с теми же
run/upper/last predicates, затемчитаетJSON толькоэтихстрок. Count/max fence,
UNION dedup, порядокID, cursor binding, поля/маскирование и read-onlyTX прежние.
Новыхиндексов/миграций/настроекPostgreSQL/записей/LLM нет.

НовыйactualPGregression временноотключаетautoanalyze толькоfixtureтаблицы
и проверяетфактическиеJSON-producing plan rows≤51, неформуSQL. Доfixонупал:
Limit51,Sort51,NestedLoop10001. Existing10001performancegateнеизменён.

Первыйcandidate:53targetunit/PGpassed55.01s, p95=16.711ms противbaseline52.639ms
на тойжеhost/fixture; Python peak258286B против260207B. Это локальныйpaired
результат, не обещаниеCI. Sourceblob/сырыеsamples вproofJSON. Finalfrozenhead
и newCI ещётребуются. API/DDL/financial/HITL не меняются; rollbackrevert.
