# T-040: граница baseline maintenance

## Поведение кандидата

Один coordinator принадлежит одному ASGI process. HTTP `/api/*` (включая GET
health и personal/session), фоновые логические операции и `/ws/audio/*` получают
lease до открытия DB connection. Child writer регистрируется до первого шага и
не наследует reentrant lease родительского HTTP task. Поддерживается один main ASGI process (штатный Compose без --workers) и отдельный
public origin. Произвольные внешние SQL/DDL и дополнительные main replicas
не объявляются безопасными: они требуют отдельного coordination contract.

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

## Межпроцессная граница и durable recovery

`personal` в Compose — отдельный uvicorn process. Все его `/api/*` HTTP,
включая health и session GET, держат shared session-level PG advisory lease
(40,0) весь ASGI lifetime, включая cleanup/commit. Background tasks/WS в этом
app отсутствуют. Перед первым эффектом main получает exclusive session lease
после local drain; queued exclusive не пропускает новые shared leases (проверено
на PG16). Ожидание ограничено30s, timeout даёт409 до pause/export/restore.
Собственный control connection сохраняется через SQL/header/CSI/cache reload,
после ошибки с эффектами удерживается до явного retry. Нет terminate чужих
connections, superuser locks, per-query hooks или нового pool.

Потеря session при crash сама по себе недостаточна. Dedicated named volume
`maintenance_control` смонтирован main rw и personal ro в `/run/cx-maintenance`;
оба получают `MAINTENANCE_CONTROL_DIR`. Он не входит в pg_dump/pg_restore.
Native default — writable `data/maintenance` данного checkout; два origins
обязаны использовать один и тот же store (явный ENV при разных checkout).
Marker имеет только version/phase/opaque job_id, без секретов и TTL. Запись:
temporary file → fsync(file) → atomic replace → fsync(directory). Незавершённый,
отсутствующий или corrupt marker закрывает public API503, даже после исчезновения
PG session. Проверка есть до подключения и повторно внутри shared lease.

Main startup при nonidle/corrupt marker закрывает admission ДО profile/provider
prepare, Sim.load_state, ABS backfill и worker/agent recovery. Создаётся только
Sim placeholder для существующего recovery endpoint; нет автоматического
возобновления actors. Bootstrap создаёт idle только для действительно missing
store, под exclusive PG lease; существующий failed/corrupt не переписывается.
CLI seed может первым инициализировать missing store тем же протоколом, затем
держит shared session lease через все commits/dump и проверяет idle. Во время
maintenance seed возвращает существующий exit4 до записи. Это защита seed от
restore overlap; одновременный destructive CLI seed и работающий main не
объявляются безопасными. Telegram bot source/runtime в этой базе отсутствуют;
его будущий HTTP inbound в main покрывается HTTP gate, прямой DB writer требует
собственного cooperative lease.

До первых DB/runtime эффектов отказ возвращает прежний ready/idle. После начала
park/restore ошибка оставляет main failed и durable marker nonidle. Устранить
причину (PG16 tools, CSI repair, права artifact/control directory) и явно повторить
существующий `POST /api/sim/baseline/restore`: только recovery HTTP допускается
при failed. Успех повторно проходит preflight и весь restore, восстанавливает
заголовки/CSI/Sim/cache и готовит свежие producers; только затем durable idle и
следующий runtime epoch открывают origins. HTTP cancellation не заменяет retry
и не удаляет marker. Аварийный рестарт не открывает доступ автоматически.

LLM/schema drift требует нового полноценного baseline dump после миграций:
обычный preflight отказывает до эффектов, после чего штатный baseline dump
доступен. `prepare_baseline.py` конвертирует archive format в отдельной scratch
DB и сохраняет provenance; одна конвертация не доказывает актуальные LLM/DB
digests и не разрешает legacy snapshot автоматически. Если несовместимость
возникла после failed restore, оператор останавливает ОБА origins, проверяет
утверждённые миграции и пересоздаёт полноценный snapshot штатным dump/seed путём
в согласованной среде. Эти операции не выполняются автоматически.

Control directory в image имеет mode1777 для isolated CI с произвольным UID;
это не authz boundary. Main — единственный rw mount, public — ro. Runtime не
chmod/chown/delete чужие existing files. Restart с тем же UID сохраняет доступ;
при смене UID и недоступном marker оператор исправляет владельца/права только
после остановки обоих origins. Rollback: остановить оба origins, завершить
валидный restore до idle утверждённой версией, затем откатить image/config;
не удалять marker/volume для обхода failed guard и не использовать down -v.

### Offline snapshot при недоступном архиве

Только после остановки обоих origins и независимой проверки корректности данных
и утверждённых миграций оператор может создать новый полный snapshot существующим
Python API. Эта команда не исправляет неизвестное состояние банка, не выполняет
seed/reset и не меняет durable marker. DB/profile выбираются существующим ENV;
секреты не помещаются в argv и не выводятся:

```bash
PYTHONPATH=backend backend/.venv/bin/python - <<'PY'
import psycopg
from app.db.session import psycopg_dsn
from app.sim import baseline
from app.sim.maintenance_db import LOCK

with psycopg.connect(psycopg_dsn()) as conn:
    conn.execute("select pg_advisory_lock(%s,%s)", LOCK)
    baseline.dump_for_connection(conn)
PY
```

В контейнерной среде используется тот же утверждённый image/ENV и shared volume
в одноразовом процессе без uvicorn. После публикации проверенного snapshot
запустить main: marker остаётся failed, public закрыт. Затем явно выполнить
существующий POST restore, который единственный завершает recovery до idle.
Не заменять эту последовательность удалением marker или ручным phase=idle.

## Проверка кандидата

До crossprocess расширения frozen200f452: полный backend4shards1224 passed,
24 skipped, exact collection/union/revision aggregate exit0; frontend161passed,
lint/typecheck; baseline86%, maintenance94%, opaque guards100% (stdlib trace).
Это историческое доказательство исходной границы, не полного нового варианта.

Durable/global targeted44passed49.37s: actual PG fairness, bounded wait,
parent cancel через настоящий SQL/header/CSI/reload; protected actual audio WS;
real child os._exit(23) после SQL/header до CSI, исчезновение PG lock и personal503
по marker, два свежих production lifespan/ASGI restart, no actors до explicit
retry, success→idle; seed-before-main bootstrap и refusal существующего failed.
После исправления неполного auth-refresh fake app полный unit923passed18skip.
Новый полный four-shard/coverage и isolated real-image smoke ещё выполняются;
этот checkpoint не объявляет T-040 готовой к merge.

Финальный maintenance freeze2a88a68: полный backend1246passed24skip, четыре
изолированных checkout/БД, exact collection/revision/union aggregate exit0.
Первый0082прогон обнаружил5fixturecollision в проверках пустого tmp_path; marker
перенесён в отдельный tmp_path_factory root без изменения исходных assertions.
Повтор guard/archive+marker24passed, новый полный четырёхчастный прогон зелёный.
Real image71passed2.6min на новом named volume, sameUID restart; первый запуск
имел только browser executable path failure до assertions, повтор с уже
установленным закреплённым Chromium1217 зелёный.
Stdlibtrace91passed: control100%, DBlease92%, coordinator92%, baseline86%,
opaque LLM/contract guards100%. Frontend161passed, lint/typecheck; licenses526.
[Машинный отчёт](T-040-maintenance-proof.json). Финальный human review и
отдельная композиция T041 ещё обязательны, общий card не отмечен done.
