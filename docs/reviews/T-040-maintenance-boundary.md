# T-040: граница baseline maintenance

## Поведение кандидата

Один coordinator принадлежит одному ASGI process. HTTP `/api/*` (включая GET
health и personal/session), фоновые логические операции и `/ws/audio/*` получают
lease до открытия DB connection. Child writer регистрируется до первого шага и
не наследует reentrant lease родительского HTTP task. External CLI и несколько
независимых backend processes не координируются этим механизмом.

Restore закрывает admission, дожидается всех допущенных операций, проверяет
совместимость архива, останавливает собственные runtime workers и соединения,
затем выполняет export/SQL restore/header restore/CSI repair/reload. Новый
AgentService/TwinService/BenchService не сохраняет старые ID, pending watermark
или task cache. Новый runtime начинает работу после открытия нового epoch.
Активный seed child или audio (включая cleanup сессии) даёт 409 до эффектов:
они не отменяются и subprocess генерации не уничтожается.

Во время maintenance обычный HTTP получает 503, второй restore — 409,
новый audio WS — close1013. Существующие DB-free GET `/api/sim/baseline` и
readonly `/ws/stream` доступны. Новые API paths/поля, проценты и миграции
не добавлены. Существующие baseline started/finished events сохраняются.

HTTP cancellation не отменяет supervised job: gate удерживается до завершения
собственных pg_restore/psql/CSI processes, восстановления заголовков и reload.
Каждый собственный subprocess ограничен 120s; timeout завершает и ожидает его.
Lifespan shutdown ожидает restore до закрытия provider/bridge.

## Совместимость и секреты

Dump и digest читают одну `READ ONLY REPEATABLE READ` exported snapshot;
транзакция остаётся открытой до завершения pg_dump, включая отмену. Snapshot ID,
DSN, ключевые байты и ciphertext не выводятся. Metadata содержит только SHA256
существующей encrypted LLM config, source DB contract/migrations, фактической
структуры всех прикладных схем (включая `langgraph`) и самого dump. Изменение
каталога/ролей/ключей, schema/source contract или legacy metadata даёт 409 до
pause/export/restore с требованием пересоздать baseline после миграций.

Два FK сохранённых sim_runs (`sim_runs_scenario_fk`, `sim_runs_llm_profile_fk`)
restore по существующему контракту возвращает `NOT VALID`; только этот флаг
нормализуется в digest. Остальные constraints сравниваются точно. Штамп
`alembic_version` не является единственным доказательством: test seed применяет
реальный SQL без такого штампа. Source0012 и реальные nonpublic checkpoint tables
меняют digest независимо, поэтому старый dump не оставит их сиротами молча.

## Recovery

До первых эффектов отказ возвращает ready и ничего не откатывает. После начала
park/restore любая ошибка оставляет admission закрытым (`failed`), без запуска
workers на частично восстановленной БД. Устранить причину (доступность PG16 tools,
CSI repair, права scratch/artifact directory) и явно повторить существующий
`POST /api/sim/baseline/restore`: этот единственный recovery HTTP допускается при
failed. Успешный retry заново проходит preflight и весь restore, пересоздаёт
workers и открывает следующий epoch. Не делать ручной UPDATE phase и не
запускать workers отдельно.

Если нужен новый snapshot вследствие миграций/config drift, обычный preflight
отказывает до эффектов, после чего доступен существующий baseline dump/prepare.
Если несовместимость появилась уже после failed restore, оператор останавливает
backend, проверяет/применяет утверждённые миграции и пересоздаёт baseline штатным
prepare CLI в согласованной среде, затем запускает backend. Эти внешние операции
не выполняются автоматически; production данным кандидат не обращается.

## Проверка

Промежуточные доказательства: coordinator/ASGI/opaque digest unit54 passed;
реальный PG16 exported snapshot, cancellation, registry drift, custom ID,
legacy refusal, nonpublic schema guard и restore roundtrip8 passed. Дополнительные
actor/WS/повторный restore и полный composed regression ещё выполняются;
этот документ не объявляет T-040 готовой к merge.
