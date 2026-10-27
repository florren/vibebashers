# T-246 — Приём CSI: POST /api/ingest/csi (JSON/XLSX), csi_responses, канал csi_survey, make import-csi

| Поле | Значение |
|---|---|
| Эпик | E20 CSI-аналитика и сеть ВСП [ЕТЗ] |
| Субагент | `SA-Analytics` (API кабинета, CSI и ВСП, индекс CX [ЕТЗ]) |
| Оценка | M (1–2 дня) |
| Волна | 8 |
| Слой | `L3` Агент и контуры (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | нет — можно отложить |
| Статус | `todo` |

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
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
