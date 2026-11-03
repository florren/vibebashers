# Freeze: полный backup/recovery synthetic БД

Результат: GREEN. Источник `cx_t092_notifications_revision` не изменён; полный архив восстановлен
только в новую собственную БД `cx_freeze_recovery_revision_20261103` на том же PostgreSQL16 / port55439.
Контекст source: root integration `c4345977d53c02e29f61a93325e3939a2178b18e`; migration head0020.
Dump/restore не заменяет и не вызывает baseline reset приложения.

## Доказательства

- Сохранены все114 пользовательских таблиц и60 sequences в4 schemas:
  public, langgraph, llm_runtime, channel_runtime. Ни одна operational schema не исключена.
- Для каждой таблицы совпали count иSHA256 всех отсортированных строк; значения
  rows/credentials/PII не записывались вreport. Сравниваются также sequences,
  namespaces/ACL, migration head, native AR иevent scopes.
- Полный schema-only dump совпал, включая ownership/grants. Нормализован только
  случайный psql restrict nonce; DDL не отбрасывался.
- Повторный read-only snapshot источника после restore совпал с исходным по
  всем114 hashes/counts,60 sequences,scope metadata иschema dump.
- Public llm_profiles: 8 строк; public llm_api_keys:
  0. Canonical profiles/configuration сохранены как данные.
- Native primary AR:3, все sourceMock. Сохранены исходы deferred/deferred/completed,
 32agent steps иrun/signal linkage. Всего agent_runs11; остальныеkind не выданы заprimary AR.
- Сохранены baseline run1 идваruntime runs2/3: stopped/paused. Их event counts237/1/9
  иsignal counts1162/2/1 совпали; orphan event run refs0.
- LangGraph populated: checkpoint_blobs363, checkpoint_writes701, checkpoints42,
  checkpoint_migrations10. Эти данные реально восстановлены, не пустая schema fixture.

## Operational ограничения

Все7 llm_runtime таблиц и6 channel_runtime таблиц пусты дои после restore.
Подтверждены ихDDL/ACL ипустое состояние; НЕ подтверждены outstanding quota
reservations, unknown/partial wire usage, reconciliation, Telegram outbox/inbound
replay/dedup или ambiguous-send recovery. Реальные ключи не декодировались;
key decryptability не проверена при0canonicalkeys.

App/actors после restore не запускались; pending/deferred/HITL не продолжались,
никаких отправок/admission/reconciliation или внешнихHTTP/LLM/TG/email не было.
Это проверка полного DB roundtrip втом жеcluster: global roles, deployment
configuration/secret files, внешниеassets иmachine-level DR не проверялись.
Runtime/baseline backup приложения намеренно исключает channel_runtime/llm_runtime;
для этой проверки использован direct pg_dump безэтихexclude, не baseline service.

## Безопасность иартефакты

Источник: READ ONLY REPEATABLE READ, pg_export_snapshot; данные/DDL иpg_dump читали
один snapshot. Table hashing потоковый, без загрузки всейБД вPython RAM.
Restore — exit-on-error/single-transaction, без--clean; существующие чужиеБД не
удалялись. Only own new destination изменялся. Roles/locale сохранены (UTF8/en_US.utf8).

- Dump: `/tmp/freeze-recovery-20261103-8uc1_v9f/full-database.dump`; 1227701 bytes; mode0600, directory0700.
- Dump SHA256: `37fb8705b83e823ed605bde5c2ceab4454405251845b15b9437b826719037081`.
- Normalized schema SHA256: `d14b8b611c4a4690240164b65fddd13a799a6090dbe319b7a72a24641d86d288`.
- Full safe proof JSON: [FREEZE-2026-11-03-full-db-recovery-proof.json](FREEZE-2026-11-03-full-db-recovery-proof.json).
- Schema dumps иstderr (еслибы возникли) остаются приватно втомже/tmp каталоге.
- Root source before/after всеchecks true. Суммарно2.047s подconcurrent
  A3functional IO; это НЕ performance acceptance илиограничениевосстановления.

Dump/SQL не добавлялись вGit иникуда не отправлялись. NativeT020 неактивирован.
