# T-270 / T-271 — проверка 30.10.2026

Ветка codex/seed-safety-visitor-name, GitHub #100 / #101. Контракты OpenAPI 1.5.7, БД без миграций. ADR-0018 и дополнение ADR-0017.

## Сохранность и baseline

- Перед обновлением сделан приватный полный dump текущего стенда PostgreSQL 16; файл 0600 вне репозитория, содержимое не выводилось.
- Dump восстановлен только в отдельную PostgreSQL 16, в cx_existing. `copied-stand.json`: новый образ, --if-needed, проверены count и digest **всех 85 таблиц** до/после, изменений нет. Старые coverage 440/480 показаны предупреждением; seed_done, настройки и данные сохранены. Baseline не подменяется живым состоянием.
- На отдельной пустой cx_seed: Alembic head, --if-needed --profile lite --clients 200 → coverage 480/480, sla_ok=True, настоящий baseline .dump (≈590 КБ), pg_restore --list успешен. PostgreSQL server 16, pg_dump/pg_restore 16.15 (PGDG bookworm).
- `roundtrip.json`: ещё одна изолированная cx_roundtrip, первоначальный seed и настоящий BaselineService.restore; после контролируемого изменения синтетических данных восстановлены все 200 активных клиентов. Основной стенд не участвовал в restore.
- Regression покрывает read-only повтор на всех таблицах и baseline bytes, другой запрошенный профиль/seed, расширение каналов, незавершённый seed, отсутствие/несовместимость tooling до записи, обязательные ошибки coverage/dump и остановку install при кодах 2/3/4.

## Представление посетителя

`browser.json` и visitor-*.png: отдельный настоящий preview :19999 с mock-агентом и синтетическим lite-сидом. Без подмены HTTP. ru/en, light/dark, ширины 1440/390; подпись «Северный ветер <demo>» / «Northern breeze <demo>» восстановлена после reload, показана текстом (HTML-тега demo нет), ответы получены от штатного агента, переполнения и ошибок JS нет.

API regression: подпись → signal.meta.visitor_name → form_context агента; client_id остаётся NULL. Чужая сессия не получает имя/историю. Проверены длина/управляющие символы, payload idempotency, сохранение при отсутствующем/null поле, удаление пустой строкой и неизменность старых сообщений.

## Команды

`make lint test` с DATABASE_URL/DATABASE_URL_TEST только отдельной тестовой БД; дополнительно tests/compliance. `npm run lint`, `npm run typecheck`, `npm test -- --run`, `npm run build` (две сборки). Для локального Node 26 использован NODE_OPTIONS=--no-experimental-webstorage, CI — Node 22. contracts_check / OpenAPI drift / i18n / owners --allow-cross, bash -n install.sh. Итоговые количества и финальная установка фиксируются в PR после выполнения.

Ограничение старого набора: read-only повтор намеренно не дописывает недостающие CSI-сигналы и не создаёт baseline из текущих живых запусков. Coverage и отсутствие такого снимка показываются явно. Для текущих данных сохранена отдельная полная резервная копия. Загрузка pg-tools во время Docker build использует официальный подписанный PGDG с проверкой TLS.

Локальный `make lint test`: 588 unit passed / 17 skipped, 121 integration passed / 2 skipped, 22 scenarios passed / 2 skipped; отдельно 31 compliance passed. Frontend: 132 passed / 22 файла, lint/typecheck и две сборки успешны. Контракты 42 схемы / 158 путей, drift 186/186, i18n 1416. После дополнительного случая незавершённого seed финальный targeted-прогон с coverage: 31 passed, покрытие четырёх модулей 88% (подробный результат — в PR); это включает новый случай сверх make-прогона.

Совместимость сохранённых payload: новый API рассчитывает старый request_hash при отсутствующем/null display_name. Отдельный regression подтверждает совпадение с форматом до обновления, повтор без дублирования и 409 при изменении подписи с тем же request_id.
