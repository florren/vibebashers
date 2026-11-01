# data/ — справочники, корпуса и сид

Все данные синтетические: имена, ники, номера карт (`card_last4` — невалидны по Луну), отзывы и диалоги сгенерированы.
Партнёры в `gifts.yaml` вымышленные.

| Файл / папка | Что | Источник |
|---|---|---|
| `federal_districts.csv`, `regions.csv` | 8 округов, 89 субъектов РФ: код (КЛАДР/ФИАС), названия, население (оценка, тыс. → чел.), условный центроид (= координаты адм. центра, пока нет SVG-карты) | составлено вручную |
| `cities.csv` | 1 121 город: регион, население, координаты, признак адм. центра | [hflabs/city](https://github.com/hflabs/city) (CC BY-SA 4.0), поля сокращены; добавлены центры новых субъектов |
| `segments.yaml`, `psychotypes.yaml` | сегменты (ТЗ 3.1) и психотипы с параметрами по `behavior/psychotype_params.schema.json` (ТЗ 4.5) | ТЗ |
| `products.yaml`, `systems.yaml`, `teams.yaml`, `channels.yaml` | продукты/тарифы/акции, 12 систем, 12 команд с профилями скорости, 11 каналов | ТЗ 3.3–3.6 |
| `product_lines.yaml` | 15 продуктовых направлений кабинета менеджера: `rate_code` → `dcltv_rates.csv`, команда-владелец, доли демо-отзывов (54 всего) | ТЗ 24.2 / ЕТЗ; данные синтетические, без брендов реальных банков |
| `error_codes.yaml` | коды ошибок (`PROC-QR-FEE-CHARGED` и др.) и типы сигналов | ТЗ 4.2, BRD |
| `sla.yaml` | матрица SLA 3×3 и правила маршрутизации | ТЗ 8.1–8.2 |
| `gifts.yaml`, `dcltv_rates.csv` | каталог извинительных подарков, экономические настройки, ставки dCLTV | ТЗ 8.5, 14 |
| `tariffs.yaml`, `rules.yaml` | тарифы Mock-АБС и бизнес-правила (`RULE-QR-FEE-001`) | BRD |
| `misselling_patterns.yaml`, `service_scripts.yaml` | паттерны misselling/conduct с примерами, эталонные скрипты | ДТЗ 22.4, 22.8 |
| `branches.yaml`, `ingest_sources.yaml`, `llm_profiles.yaml` | 10 исходных ВСП сценариев 9/10, расширяются провайдером до 240 × 6 сотрудников; адаптеры, профили LLM | BRD, ТЗ 3.7, 5.2 |
| `templates/notifications.yaml` | Jinja2-шаблоны уведомлений по сегментам | ТЗ 8.4 |
| `scenarios/*.yaml` | 11 демо-сценариев | ТЗ 18 |
| `corpus/signal_templates.yaml` | шаблоны текстов сигналов 10 типов × 4 продукта + сарказм/сленг/опечатки | — |
| `corpus/mock_feed.yaml` | 30 постов mock-ленты соцсетей/отзывов (сценарии 8, 11) | — |
| `import/transcripts/` | 20 транскриптов (10 JSON по `ingest/transcript.schema.json` + 10 TXT), `scenario10_retail.txt` | `scripts/seed/gen_corpora.py` |
| `bench/*.jsonl`, `bench/transcripts_v1/` | sentiment_v1 (300), hidden_negativity_v1 (120), summary_v1 (60), red_phrases_v1 (139), golden_v1 (120), эталоны транскриптов | `scripts/seed/gen_corpora.py` |
| `cassettes/` | записи LLM для офлайн-replay | — |

## Шрифты UI (T-263)

Бинарники Inter (400–700, latin + cyrillic) и JetBrains Mono (400, 500) лежат в `frontend/public/fonts/` (формат woff2).
Источник: официальные релизы [Inter](https://github.com/rsms/inter) и [JetBrains Mono](https://github.com/JetBrains/JetBrainsMono), лицензия OFL 1.1 (`docs/LICENSES.md`). В рантайме внешние CDN не используются. Полные copyright/OFL notices поставляются рядом с бинарниками: `Inter-OFL.txt`, `JetBrainsMono-OFL.txt`. Проверка после build проверяет все 12 файлов и каждый `@font-face`; Playwright `e2e/fonts.spec.ts` блокирует внешнюю сеть и через Chromium CDP проверяет фактические custom-font glyphs латиницы/кириллицы во всех весах.

## Сид

```bash
python scripts/seed/run.py --profile lite|demo|stress [--seed 42] [--reset-history] [--refs-only]
```

Идемпотентен: справочники — upsert по коду, клиенты и история создаются один раз (`settings.seed_done`).
Профили: lite 1 000 клиентов / 800 сигналов / 150 инцидентов; demo 5 000 / 2 500 / 400; stress 20 000 / 10 000 / 1 500 (ТЗ 4.4).
После сида считается матрица покрытия (`settings.coverage`): каждая комбинация тип × продукт × канал ≥ 1 сигнал, каждая ячейка SLA ≥ 5 инцидентов
в разных статусах, доля «трудных» текстов (сарказм/сленг/опечатки/капс) ≥ 25 %, 3–5 % операций card_payment/qr_sbp с `PROC-QR-FEE-CHARGED`, у 60 % клиентов `social_handles`.
История пишется в `sim_runs` kind=`baseline` («История 14 дней (сид)»); `sim_state.current_run_id` указывает на неё, пока симулятор не создаст новый запуск.

### Красные слова (T-239)

`red_words.yaml` — версионированные правила (`rules-change`) для клиентского текста, отдельно от детектора речи сотрудника. Журнал совпадений с диапазонами и версией хранится в `ingest_messages.payload.meta.red_words`; колонки `meta` у `ingest_messages` нет. Сигнал содержит `red_words`, флаг `red_word`, копию аудита в `signals.meta`; `v_signal_normalized` отдаёт признаки для UI. Юридические категории требуют HITL, категория misselling сама по себе не является юридической угрозой.

### Сеть ВСП v2 (T-245)

Сид по умолчанию создаёт 240 ВСП по 89 регионам, 19 закрыты; десять исходных кодов и сотрудники сценариев 9–10 сохраняются. Адреса новых данных — явно синтетические, сотрудники генерируются из локальных списков имён, образование и стаж — учебные. Сеть детерминирована seed и сим-датой; новые ВСП используют отдельный RNG и не меняют поток случайных чисел клиентов. `scripts/seed/run.py --seed N` задаёт seed явно, без аргумента берётся `sim_state.seed` (для чистой БД — 42).

`BranchDirectoryProvider`: `synthetic` и `snapshot_file`; `scripts/seed/run.py --refs-only --branch-provider snapshot_file --branch-file data/import/branches/example.json` (также CSV). Файлы только из `data/import/branches/`, до 10 MB/10 000 строк. JSON содержит массив или `{branches:[...]}`, CSV — те же имена столбцов и JSON-массив в `product_line_codes`. Даты с часовым поясом; неизвестный город/регион/направление, повтор кода или замена исходного сценарного ВСП отклоняются с номером строки. Сетевых вызовов нет. Имена руководителей из snapshot не импортируются. Отсутствующие ВСП не удаляются из БД: становятся закрытыми, исторические FK сохраняются. История пересчитывается за 12 сим-месяцев по всей сохранённой сети. Snapshot — источник справочника, а не сотрудников или посещений.

`regions.csv.okato`: коды регионов первого уровня ОКАТО (11 знаков с нулевым дополнением), для автономных округов — соответствующий второй уровень. Основа — уже используемый [hflabs/city](https://github.com/hflabs/city) (CC BY-SA 4.0), региональные коды Ненецкого АО `11100000000`, ХМАО `71100000000`, ЯНАО `71140000000` сверены с [таблицей Росстата](https://www.rosstat.gov.ru/storage/mediabank/met_519-22092025.pdf). Для кодов 90/93/94/95 в используемом источнике нет подтверждённых соответствий: CSV пусто, в БД NULL; неподтверждённые ОКАТО не подставляются. Соответствие `ОКАТО → regions.code` задаётся этой же таблицей.

`GET /api/branches` — курсор по коду, фильтры region_code/status; `GET /api/branches/network` — агрегат сети, 1–24 месяца. Cache-Control: private, max-age=86400. Признак synthetic соответствует источнику, Telegram chat ID в ответ не попадает. Дамп baseline включает расширенные branches/employees и branch_network_history; dump/restore проверяется integration-тестом.

### CSI import (T-246)

`make import-csi FILE=data/import/csi CX_BASE_URL=http://localhost:8000` sends JSON objects/arrays and XLSX files to `/api/ingest/csi`; no database writes bypass the normalizer. `scripts/seed/gen_csi_sample.py` regenerates the two deterministic synthetic sample files (identical CSI IDs deliberately demonstrate deduplication). XLSX uses read-only parsing with XML entities disabled; input limits are 10 MB / 10 000 rows. Russian headers, decimal commas and Moscow-local dates are supported; timestamps are normalized with a timezone.

Each accepted row creates one signal and one `csi_responses` record in the same transaction. An invalid row does not discard valid rows: HTTP 422 includes a partial `report` with row/column/field; correcting and resending the file is safe. Rejected audit records omit raw values and unknown fields. Employee identifiers must refer to synthetic employees of the selected branch; names and contacts are not accepted. `signals.geo` includes the VSP code and regional OKATO; the public UnifiedMessage schema remains compatible.

Migration `0007_csi_audit` supports the CSI signal primary key and the composite visit-aggregate key in `db_activity_log`. Repeating the seed backfills details only for legacy synthetic CSI history of the current run, preserving signal IDs/status and the enclosing transaction. Archived runs are not changed. Migration downgrade retains the compatible audit function; no CSI data are deleted.

### Предыстория операций (T-017)

`op_paths.yaml` задаёт 14-дневное окно, op_type/system_path, положительные часовые
и недельные веса, относительную интенсивность сегментов и параметры логнормальных сумм.
Время интерпретируется в часовом поясе переданного `sim_time`, включая неполные часы.
Общий объём нормирован по фактическому составу сегментов: `lite` — около 24 операций
на клиента, `demo`/`stress` — около 120. Поэтому demo5000 даёт около600000 операций,
а stress20000 — около2400000. Операции передаются в PostgreSQL потоком COPY;
в памяти остаются клиенты/продукты и336–337 часовых интервалов, не вся история.

Доля failed —1%; error_code выбирается только из систем пути и совместимого продукта.
Отдельно сохранена модель BRD ошибочной комиссии у4% успешных QR-платежей
(это не политика возврата и не дополнительные failed). Новая генерация использует
синтетические названия мерчантов. Повторный seed сохраняет существующий run целиком;
для изменения конфигурации используйте новый пустой тестовый банк. Данные работающего
стенда автоматически не перегенерируются. У каждого нового клиента1–4 продукта,
карточные terms содержат только masked_number вида `**** 1234`.

Проверка конфигурации без записи в БД:
`backend/.venv/bin/python scripts/seed/operations.py --profile lite --check`.
