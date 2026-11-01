# T-108: contract-change, обязательный human review

OpenAPI 1.5.14: RunId на всех трёх engine/db GET; table filter у activity; nullable simulation run_id в DbActivity; exact marker у counts. current = baseline + current, numeric = baseline + выбранный, all — явный запрос. Unknown historical run — 404. Legacy audit без run_id виден только в all. Данные rows и activity ограничены allow-list; incident_signals добавлен для обязательной цепочки из карточки.

DB: 0011 добавляет nullable db_activity_log.run_id и индекс (run_id,id). FK намеренно нет: DELETE/run removal не уничтожает доказательство аудита. Старые записи не переписываются и не получают выдуманный run_id. Триггер сохраняет actual simulation run, для agent_steps разрешает agent_run→sim_run; связки/история инцидента берут incident.run_id. Добавлены отсутствующие триггеры обязательной цепочки и разрешённых таблиц. Summary новых записей хранит только changed_fields, исключая значения произвольного JSON, контактов и секретов. DELETE сохраняет run_id основной строки; дочерняя каскадная запись после удаления родителя может остаться с null и честно видна в all.

Изменение аддитивно, rollback приложения не требует удаления audit evidence. Для возврата старой trigger implementation нужна отдельная review migration; downgrade не удаляет историю. Полные старые summary маскируются при чтении, а не переписываются в БД.

Зависимости интеграции: T-067 / PR #152 (1.5.12) и T-091 (1.5.13) pending review; этот diff от main 3c1c12c не отменяет их input bounds/429/Client360 RunId. При merge сохранить оба предшествующих diff и итоговую версию ≥1.5.14. DB migration number0011 согласуется с интегратором.

Merge запрещён до human review контрактов. API только читает; никаких arbitrary SQL, LLM, уведомлений или поддельных audit INSERT.
