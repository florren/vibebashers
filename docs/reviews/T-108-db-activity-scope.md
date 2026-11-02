# T-108: contract-change, обязательный human review

OpenAPI 1.5.14: RunId на всех трёх engine/db GET; table filter у activity; nullable simulation run_id в DbActivity; exact marker у counts. current = baseline + current, numeric = baseline + выбранный, all — явный запрос. Unknown historical run — 404. Legacy audit без run_id виден только в all. Данные rows и activity ограничены allow-list; incident_signals добавлен для обязательной цепочки из карточки.

DB: 0011 добавляет nullable db_activity_log.run_id и индекс (run_id,id). FK намеренно нет: DELETE/run removal не уничтожает доказательство аудита. Старые записи не переписываются и не получают выдуманный run_id. Триггер сохраняет actual simulation run, для agent_steps разрешает agent_run→sim_run; связки/история инцидента берут incident.run_id. Добавлены отсутствующие триггеры обязательной цепочки и разрешённых таблиц. Summary новых записей хранит только changed_fields, исключая значения произвольного JSON, контактов и секретов. DELETE сохраняет run_id основной строки; дочерняя каскадная запись после удаления родителя может остаться с null и честно видна в all.

Изменение аддитивно, rollback приложения не требует удаления audit evidence. Для возврата старой trigger implementation нужна отдельная review migration; downgrade не удаляет историю. Полные старые summary маскируются при чтении, а не переписываются в БД.

Зависимости интеграции: T-067 / PR #152 (1.5.12) и T-091 (1.5.13) pending review; этот diff от main 3c1c12c не отменяет их input bounds/429/Client360 RunId. При merge сохранить оба предшествующих diff и итоговую версию ≥1.5.14. DB migration number0011 согласуется с интегратором.

Merge запрещён до human review контрактов. API только читает; никаких arbitrary SQL, LLM, уведомлений или поддельных audit INSERT.

## Согласование и интеграция 02.11.2026

Пользователь подтвердил контракт PR164 после зелёногоCI. Обычный merge main d2a4026 сохраняет Compare5000/20RPM, Client360scope, TraceGraph и общуюверсиюAPI1.5.16. В Engine одновременно доступны DB и Compare, их самостоятельныевкладки скрывают списокAR; WSruns инвалидирует иdb,иtrace. Миграция0011 сохранена. В конфликтеbaselinefixture принят dynamicAlembichead +SimRunscommentregression изPR174; старый dashboardSQL не вернуливместо актуального analytics.dashboard.

После composition:196frontend, Ruff359/mypy255, drift192/192,140targetunit4.61s и14PGDB/Trace/Compare97.09s green. Первый lint дошёлдоdrift и остановился из-за отсутствовавшегоopenai вcanonicalvenv; sharedvenv не менялся, использован готовыйSDKvenv, drift+targets повтореныуспешно. ExactnewheadCI обязателенпередmerge.

## CI regression после T-017 и композиция main8b225d5

Source bd8ebae, job125092379734: `test_db_activity_chain_isolation_masking_and_idempotent_migration` падал на отсутствии `incident_signals` после агентского прохода. До исправления это воспроизведено локально на отдельной cx_t108_composed_revision (1failed,6.50s), после ordinary merge main8b225d5 (composition3e30533).

Фикстура неявно рассчитывала на неуспешный вклад у первого mass-клиента. Профильная история T-017 этого не обещает; unrelated QR не может быть причиной жалобы про вклад. Дополнительно helper по умолчанию использовал wall clock, а seed/sim_state — фиксированную дату симуляции: новые операции09Nov не попадали в context обращения02Nov. При привязке к правильной дате необходимо также учитывать существующую14-дневную политику повторного HITL.

Исправление только в тестах: helper получил необязательный sim_time с прежним defaultNone; этот case явно использует sim_now, mass-клиента без предыдущего tech_fault за14дней, понятную техническую жалобу и настоящие faileddeposit операции в old/current runs. Более новая failedQR — decoy; проверяются error_code иoperation_id именно вклада иownership двухrun IDs. Исходные audit/DBAPI assertions сохранены, в том числе порядок incident→link→history→notification, DELETE evidence, masking, old/current/all/no-current, cursor иstatus-коды. Production policies, HITL, APIallowlist, контракты и immutablebaselineT017 не менялись.

После исправления: 60 actualPG/relatedunit passed19.70s, включая оба DBAPI/migration tests и safety/refund/baselinecompatibility. Make lint:196frontendpassed, Ruff366files/mypy256modules/drift192. Contracts/i18n/TS/tasksgeneration проверены отдельно. Полный прежний backendproof остаётся привязан к его прежнему source; этот boundedtest-onlyfix не выдаётся за новый полный backendrun. Exact-head CI обязателен после push родителем.
