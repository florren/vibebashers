# T-040: lifecycle и API1.5.15 — draft для review

До merge обязательны полный regression и human review: AGENTS.md §6 (деньги/HITL) и §7 (contracts). Этот checkpoint не готов к merge.

## Контрактный diff

- OpenAPI1.5.14→1.5.15 сохраняет T0673–5000/20RPM/429, T091Client360 RunId и T108DB scope/nullablelast_change_at.
- SimRun.kind и filterkind в истории дополнены уже существующим DB/runtime видом live. POST создания по-прежнему принимает только free/scenario.
- Scenario получает optional reset_mode_required (baseline|null) из YAML и runnable:boolean. UI показывает ограничение из источника и не предлагает недоступный вход. Для сценариев1/4/7 существующее требование baseline теперь исполняется до эффектов; counters/none возвращают409. Внутренний DemoExecution явно выбирает требуемый baseline, что удаляет данные прошлых запусков по уже установленной политике сброса; summary/JSON сохраняются.
- Эквивалентный scenarios/{id}/run документирует optional seed/llm_profile_id, уже предусмотренные созданием SimRun.
- Для archived-run CSV недоступен (409): события удалены; JSON возвращается из проверенного сохранённого файла вместе с прежними агрегатами.

DTO/пути не переименованы, новой миграции нет (используется T1080011).

## Операции с данными и ограничения

Archive/delete разрешены только для завершённого неbaseline/нетекущего run без выполняющегося agent. Принадлежность определяется FK к sim_runs, а не именем run_id. Любая ссылка извне удаляемой области приводит к409 до purge. Для защиты от гонок записи блокируются на время операции с lock timeout5s; сами данные удаляются одним statement с проверкой FK-циклов. Audit без FK сохраняется. Удаление заголовка обнуляет parent_run_id у его сохранённых потомков; готовый JSON не удаляется.

Archive сохраняет JSON с summary/агрегатами до purge, fsync и exclusive link, не перезаписывает отличающийся файл/символическую ссылку. При ошибке DB собственный новый файл убирается. Идентичный orphan от прерванной попытки пригоден для retry. Повтор читает/проверяет run.id и summary; недоступный/повреждённый архив — явный отказ. Отдельное соединение исключает внешний незавершённый transaction вокруг filesystem effect.

Перед baseline restore прежние run экспортируются; archived выставляется заголовкам только после успешного pg_restore. При отказе restore экспорт сохраняется, готовность нового run не объявляется. Восстановление удалённых raw rows возможно только из заранее сделанного DB backup: JSON содержит summary/агрегаты, а не полный backup. Поэтому пользователь должен явно выбирать archive/delete/reset, UI обязан показывать последствия.

**Уточнение составного P1/T-051 (API1.5.18/0013):** описанный ниже initial SimRun snapshot остаётся metadata. Исполнение новых AR получает current role snapshot, begun/resumed AR — собственный frozen snapshot. Только explicit SimRun main override использует initial main parameters; fast/twin актуальны на новый AR. Supplementary tariff projection использует actual AR execution role; recorded cost не пересчитывается. При no-LLM trace нет фиктивного model execution. Подробный проверяемый diff и ограничения — `T-051-runtime-profiles.md`; исторические цифры проверок ниже не являются проверкой P1.

При создании запуска сохраняется private snapshot профилей main/fast/twin, их ID, моделей, sampling options и тарифов. Execution агента (включая resume/followups), двойников и эмулятора команд получает независимые role bindings; общий chain не меняется. Смена глобального каталога не меняет уже начатый запуск. Записанная стоимость не пересчитывается; дополнительная оценка по тарифу использует снимок запуска, а compare/bench сохраняют свой явный выбор. Это прежняя формула per-million, без изменения ставок или лимитов. Нулевой тариф снимка не подменяется новым тарифом из каталога.

Mock/replay охватывают все роли и исключают live providers. Secrets и credentials в URL/extra, невалидные тарифы отклоняются до записи снимка; ключи остаются в существующем secret storage. Неактивный/отсутствующий/bench_only профиль не допускается для запуска. Для legacy без снимка исторические настройки восстановить нельзя: сохраняется явная конфигурация вызывающего кода; историческая точность не утверждается.

Целевые проверки снимка/chain:44 unit passed;12 PostgreSQL passed (profiles/summary/jury); после дополнительной проверки bench_only —3 PostgreSQL passed. Дополнительный прогон с coverage:24 passed51.84s (unit profiles + PostgreSQL profiles/lifecycle), run_profiles.py99/108 statements=92%. Полный make lint зелёный:144frontend,338format,247mypy,OpenAPI191/191. Полный итоговый regression ещё не выполнен. Maintenance concurrency и защита LLM-каталога от отката baseline дорабатываются отдельно. Stopped-resume guard/checkpointer относится также T041. Окончательный review будет записан в PR после реализации.

Составной T094 regression выявил три совместимости. Legacy без snapshot с явным Mock-профилем теперь сохраняет переданные model/тарифы для всех offline-ролей; live provider по-прежнему исключён. Новые pinned Mock-тарифы не переопределяются. T065 fixture явно моделирует legacy run и сохраняет прежний ненулевой pricing assertion; новый frozen snapshot тест сохраняет0 при последующей смене каталога на9. Replay fixture явно выбирает offline replay и сохранённую GigaChat-3-Pro для всех ролей до нового run, вместо ожидания override уже закреплённого Mock. Все replay/ledger/assertions и кассеты сохранены. CSI test сохраняет stopped предыдущего run перед restore_started; проверяет обе restore-фазы в порядке и отсутствие повторного stopped на втором restore. CSI repair440→480/40added проверяется прежними assertions. Итог18unit/PG passed32.72s на выделенной cx_run_lifecycle_revision. Полный состав после этих исправлений ещё повторяется.
