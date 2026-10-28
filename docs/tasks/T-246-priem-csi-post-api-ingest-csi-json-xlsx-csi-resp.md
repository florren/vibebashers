# T-246 — Приём CSI: POST /api/ingest/csi (JSON/XLSX), csi_responses, канал csi_survey, make import-csi

| Поле | Значение |
|---|---|
| Эпик | E20 CSI-аналитика и сеть ВСП [ЕТЗ] |
| Субагент | `SA-Analytics` (API кабинета, CSI и ВСП, индекс CX [ЕТЗ]) |
| Оценка | M (1–2 дня) |
| Волна | 8 |
| Слой | `L3` Агент и контуры (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | нет — можно отложить |
| Статус | `in_progress` |

## Цель
CSI-обращения превращаются в сигналы только через нормализатор (правило 17), ТЗ 25.1–25.2.

## Разделы ТЗ (docs/TZ.md)
§25.1, §25.2, §3.7

## Контракты
- `events/ingest/csi_response.schema.json`
- `api/openapi.yaml: POST /api/ingest/csi`
- `data/import/csi/`

## Зависимости
- Зависит от: [T-237](T-237-kontrakty-kabineta-csi-i-vsp-migraciya-0005-open.md), [T-207](T-207-edinaya-shema-soobscheniya-i-normalizator-ingest.md)
- Блокирует: [T-247](T-247-korpus-csi-csi-v1-300-zhalob-csi-visits-agg-znam.md), [T-248](T-248-api-analitiki-csi-i-vsp-korrelyacii-scatter-dolz.md)

## Что сделать
1. Парсер JSON и XLSX (`openpyxl`, режим read-only): сопоставление столбцов по заголовкам ЕТЗ 7.2, нормализация чисел и дат, ошибки — 422 с номером строки и столбцом.
2. `from_csi()` в `app/ingest/normalizer.py` → `UnifiedMessage` (канал `csi_survey`, `geo.vsp_code`) → сигнал; подробности — в `csi_responses` (1:1); идемпотентность по `CSI-XXX`; журнал `ingest_messages`.
3. Цель `make import-csi` (Makefile — метка cross-layer, как у `import-transcripts`), образцы `data/import/csi/*.xlsx|json` (синтетика); импорт 1 000 строк ≤ 10 с.
4. Тесты: повторная загрузка не дублирует, битая строка не роняет весь файл (частичный отчёт), прямые INSERT мимо нормализатора запрещены (тест AGENTS rule 17).

## Критерии приёмки
- [ ] Повторная загрузка файла не создаёт сигналов; ошибки указывают строку.
- [ ] Каждый сигнал `csi_survey` имеет 1:1 `csi_responses`.
- [ ] Нет ПДн сотрудников и клиентов.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/integration/test_ingest_csi.py
make import-csi
```

## Отчёт субагента
Ветка `feat/T-246-csi-ingest`, от main `7e72311` (T-245 принят в #69). JSON/XLSX → `from_csi` → публичный `create_signal`, атомарные signal/detail/journal, частичный отчёт 422 со строкой/столбцом, безопасный повтор исправленного файла. Проверяются ВСП и принадлежность синтетического сотрудника; неизвестные поля/ФИО отклоняются и не сохраняются в журнале отказов. Числа с десятичной запятой и даты MSK нормализуются; XML entities запрещены, лимиты 10 MB/10 000 строк/50 MB распакованного XLSX.

Сид CSI использует тот же нормализатор в транзакции вызывающего кода без промежуточного commit; regression-тест проверяет rollback и невидимость незакоммиченных строк. Повторный сид дополняет только старую синтетическую историю текущего run, сохраняя ID/статусы; архивы не меняются. `0007_csi_audit` исправляет ключи аудита CSI и составной ключ visits; downgrade не удаляет данные и сохраняет совместимую функцию.

Контракт вперёд: OpenAPI 1.5.1 (JSON array, multipart, отчёт), три необязательных поля CSI; Python/TS и копии схем сгенерированы. cross-layer: L1 контракты/миграции/CI/Makefile, L2 сид и справочные файлы, L4 сгенерированные типы, L5 лицензии. Общие изменения разрешены пользователем.

Проверки: parser/API **31 passed**; 1000 строк **2.139 s** (порог 10 s), повтор без дублей. Реальный `make import-csi` на изолированной БД: JSON accepted=2, XLSX duplicates=2, повтор обоих duplicates=2. SQL schema + миграции 2–7 дважды, downgrade 3 / upgrade head / alembic check зелёные. Frontend Node 22: lint/tsc/**33 tests**/build/gen:types; contracts **41/149**, drift **175/175**, i18n **1032**.

Общий lint зелёный, unit **426 passed / 16 skipped**. Нестабильный тест mock benchmark сравнивал wall-clock latency двух запусков; часы подменены только внутри unit-теста, все assertions и независимая проверка реального времени ≤30 s сохранены. Финальные integration/scenarios и CI проверяются перед merge.
