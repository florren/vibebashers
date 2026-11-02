# T-276: проверка настоящего PG18 baseline на изолированной PG16

Проверяемая версия кода: `e586ed068ae152ded7bc24921c133c0152c65d98`, база
`d1710be1219a5f722335f9e478b50c4f73c62f6b`. Дата: 02.11.2026.
Машиночитаемое доказательство: [T-276 proof](T-276-legacy-baseline-proof.json).

## Источник и ограничение доказательства

Исходный исторический архив найден в `/tmp/reset-seed-baseline-before/lite.dump`
(другая идентичная копия — `/tmp/cx-baseline-deploy/lite.dump`). SHA256 **точно**
совпадает с уже записанным в `docs/BASELINE-COMPATIBILITY.md`:
`efd316e8b838d0e007f9120c488570c7da0dcc5641f9c8a3516b051d1f1b9193`.
Это архив от прежней проверки, не вновь изготовленный PG18 substitute.

Заголовок: format 1.16, database 16.15, pg_dump 18.6. Штатный pg_restore 16 возвращает
exit 1 `unsupported version (1.16) in file header`. В canonical data/baseline
нынешние файлы уже PG16; они **не** использовались вместо исторического источника.
Provenance совместимого canonical архива ссылается на другой source SHA: fail-closed
проверку не обходили и существующие sidecars не исправляли.

Создана отдельная копия original с проверкой SHA. Оригинал/canonical/их sidecars
не менялись. Архивы и raw-данные не добавлены в Git. Конвертация и восстановление
выполнялись только в собственных одноразовых `cx_t276_convert_revision` и
`cx_t276_verify_revision` тестового PG16. ENV_FILE=/dev/null, явные own URLs и
PYTHONPATH своего checkout, mock LLM, frozen готовый SDK venv без установки deps.

## Найденный дефект и минимальное исправление

Конвертер создаёт отсутствующую в старом архиве `sim_runs` из canonical CREATE
TABLE, но пропускал её canonical COMMENT. Actual `obj_description` был NULL;
`alembic check` обнаружил add_table_comment и вернул 255. Остальная проверенная
схема совпадала.

Теперь конвертер также исполняет **точную** строку COMMENT ON TABLE sim_runs из
`contracts/db/schema.sql`, без дублирования/изобретения текста и изменения
contracts/models. Existing real-DB regression проверяет комментарий против
сгенерированной модели; проверка Alembic head использует ScriptDirectory, а не
устаревающую константу0010. Все прежние assertions сохранены.

## Проверенная последовательность

1. pg_restore 18 читает только source copy; SQL исполняет psql 16. pg_dump 16 создаёт
   новый prepared-comment-fixed.dump; прежний prepared.dump сохранён отдельно.
2. Source SHA до/после одинаков. Новый output SHA:
   `d3e797d483c68cc8264821f3d7dacf5ee260021bc7de067223b54af0ae457ea3`.
   Сохранены original provenance и checksum; повторная запись output запрещена.
3. Два восстановления pg_restore/psql 16 дают те же агрегаты: 200 clients,
   800 signals, 150 incidents, 2176 operations, 1 восстановленная запись sim_runs.
   Неизвестные исторические сведения не изобретались: сохраняется явная пометка
   конвертера о восстановленной минимальной метаинформации.
4. Текущий Alembic head 0010 подтверждён динамически. Canonical комментарий совпал;
   `alembic check` после исправления exit0, no new upgrade operations detected.
   Дополнительно read-only проверены 183 FK: orphan-ссылок 0; public tables 85
   (включая alembic_version).
5. CSI repair после каждого restore: total 480, after 480, added 0. Это число
   обслуживаемых CSI-обращений по repair, не число строк csi_responses (их 69).
6. Намеренная SQL-ошибка после restore SQL дала ошибку, а собственный scratch
   marker сохранился благодаря rollback. Следующая штатная попытка успешна,
   marker исчез, агрегаты совпали.
7. Отказ при nonempty scratch и при source/output overwrite проверен; исходные
   hashes сохранились, новый output при отказе не возник.

Конвертация по секциям изменяет только одноразовую БД и не обещает общий rollback
всего converter. После её сбоя scratch пересоздают; output не публикуется. Первую
попытку остановил отсутствовавший в test-tool directory psql 16; только собственная
partial scratch была пересоздана. Проверенный psql 16 взят из уже существующего
тестового контейнера. Никакие SQL-ошибки не подавлялись.

## Проверки и применение

Targeted unit/real-DB: **4 passed**, 12.28 с. `make lint`: exit0, 25.12 с.
Полный sequential `make test`: exit0, 1266.22 с. **1423 backend passed, 24 skipped**:
1112 unit/18 skip; 238 integration/4 skip; 42 scenarios/2 skip; 31 compliance.
Frontend: **173 passed**. `make licenses-check`: green, 530 distributions.
Проверки не шли параллельно внутри checkout. Новых dependencies не добавлено.
Покрытие добавленных executable строк конвертера: **4/5 = 80%** (stdlib trace
с фильтром абсолютного co_filename, без basename ignore cache). Не покрыт только
защитный отказ при удалённом из canonical schema COMMENT. Повтор targeted
под trace: 4 passed, 13.14 с.

Реальные внешние LLM не вызывались: разрешённая граница — format/schema tooling,
синтетический offline архив и scratch PG. Совместимость будущих LLM/AR profiles
из этого прогона не выводится.

Доказательство ограничено указанным commit/current schema 0010. Новые цепочки
T040/T041/P1 (0011/0012/0013), baseline contract/config fingerprints требуют
**новой** revalidation после композиции. Форматная конвертация сама по себе не
создаёт их runtime metadata. Этот prepared archive не назначен canonical и не
применялся к пользовательскому стенду. После review оператор самостоятельно
выбирает проверенный путь; архив нельзя автоматически подменять в рабочем каталоге.

Recovery для operator-owned conversion: сохранить original и его SHA; проверить
exit code и наличие/соответствие provenance; при ошибке не назначать output рабочим
baseline. Пересоздать только заранее выделенную conversion scratch-БД и выбрать
новое имя output (прежние артефакты сохранить для разбора). Подготовленный архив
проверить в отдельной verification scratch-БД. Ни удаление canonical sidecars,
ни правка hash/header не являются способом восстановления совместимости.
