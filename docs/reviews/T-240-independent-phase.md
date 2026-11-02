# T-240: независимая фаза корпуса, CLI и pure history

База: T019 `96caa2a596828ccf442a45160246a5bdbb56d082`, frozen checkpoint `400d85f`. Это checkpoint перед
композицией с P1, **не завершение T240**. [Машиночитаемые проверки](T-240-independent-proof.json).

## Корпус и приём файлов

`data/corpus/reviews/product_lines_v1` содержит 162 самостоятельных синтетических
русских отзыва: точное тройное распределение исходных 54 по 15 направлениям.
Тексты не размножены общим padding; gold содержит направление и criticality.
Manifest фиксирует версию, source SHA, reference anchor и явные коэффициенты
синтетической сезонности/jitter/spike. Они не являются поведенческой policy,
экономическими коэффициентами или калибровкой реального банка.

В `data/platforms.yaml` пять типов нейтральных площадок с ru/en названиями без
URL/HTML. Seed-корпус принимает только HTTPS `.invalid` source URL; проверенный
loader проверяет manifest/hash/аннотации/доли. Общий локальный import принимает
HTTP(S) provenance URL без credentials и **никогда его не запрашивает**.
Доступный future producer helper возвращает только известный display object,
не raw meta/URL; неизвестный или нетипизированный код даёт None.

CLI `scripts/import_reviews.py` по умолчанию делает dry-run. Запись требует
`--apply`, явный `--run-id` и DATABASE_URL в окружении. JSON/CSV/XLSX отображаются
в тот же UnifiedMessage и проходят только normalizer. Дата передаётся как aware
sim_time; date-only требует timezone, Excel date cells — явной ISO-строки.
Оригинальные date/source_url/platform сохраняются в meta. Gold никогда не входит
в сообщение, classification или prompt. Source/external identity разделена по
run; повтор и конкурентный повтор не создают новые сигналы. Весь файл — одна
транзакция, включая регистрацию file source без фонового polling.

Парсинг ограничен размером/числом строк/столбцов и распакованного ZIP; XLSX
использует defusedxml/read_only/keep_links=False, запрещает формулы. Реальный
workbook с external relationship проверен при запрещённых DNS/connect: берётся
текст ячейки, hyperlink target не используется. Есть синтетические JSON/CSV samples.

## Seed projection и история

Seed-only projection вынесена из runtime importer. Она требует внешнюю
транзакцию и baseline-kind run, заполняет физическое направление/уровень, не
понижает criticality при red words. Она не создаёт signal напрямую и не commit'ит.
План даёт 180 уникальных direction×channel delivery identities; фактические
CSI/audio context и settings.coverage wiring **ещё не реализованы**. Старый
T019 type×product×channel код не менялся.

Pure history строит 12 календарных месяцев из явных seed/run/anchor/actual input
через SimRng. Пересекающие последние 14 дней месяцы содержат только actual rows,
имеют coverage interval/partial flag. Тест всех 15×source×severity ячеек даёт
точное 0% tail deviation. Это **pure fixture proof**, не доказательство хвоста
перегенерированного baseline. Более ранние месяцы — явно синтетические агрегаты;
fault-spike months передаются явно, не выдаются за реальные incident/release.
Неизвестное направление отчётно учитывается отдельно, не назначается по догадке.
`loss_rub=None`, финансовые потери не изобретаются.

Перед реальным seed нужны также доверенные sentiment annotations/фактическая
classification для negative_count. Текущая утверждённая projection заполняет
только направление/уровень: выводить sentiment из criticality нельзя. Этот
остаток необходимо решить явно при seed composition, не выдавать unknown за
наблюдённую нейтральность/нулевой негатив.

## Проверки и следующая фаза

- **45 targeted passed**, включая 5 actual-PG: 162 imports, preserved dates/meta,
  duplicates/foreign-run identity, rollback invalid CSI, baseline-only gold,
  red-word priority, concurrent duplicate, настоящий CLI JSON/CSV/XLSX.
- Полный unit suite: **1185 passed, 18 skipped**, 34.31 с.
- Новое ядро/CLI: **487/515 executable lines = 94.56%**; каждый файл ≥90%.
  Stdlib trace использует абсолютный co_filename, без basename ignore cache.
- Ruff app/tests + CLI green; format 369 файлов; mypy app 257 файлов green.
  Licenses-check green, 530 distributions, новых deps нет.

Тесты использовали только собственную cx_t240_corpus_revision на scratch PG16;
ENV_FILE=/dev/null, mock, абсолютный PYTHONPATH, frozen SDK venv read-only.
Рабочие/production данные и внешние LLM не использовались.

После stable P1: обычный merge, migration0014 после фактической0013. История должна
получить run_id FK/cascade, новый unique(run,line,month), nullable legacy owner без
guess-backfill; новый INSERT/UPDATE требует известный положительный owner. Нужны
partial/coverage typed columns и nullable unknown loss с согласованным consumer.
Пока DDL-файла с отсутствующим parent нет.

Далее: CLI shared maintenance lease/control cooperation, seed normalization с
валидными CSI/audio context, обе coverage dimensions, actual history tail/reseed/
dump/restore proof; forward API1.5.19 source_platform producer + generated types
и ru/en text-only UI. До этих проверок UI, весь T240 и future schema compatibility
не объявляются готовыми. Полный composed suite остаётся обязательным.


Последующая delta не переписывает приведённые здесь исходные hashes/проверки:
[editorial sentiment revision2](T-240-sentiment-annotation-review.md). Там отдельно
зафиксированы новые labels и разрешённая baseline-only sentiment projection.
