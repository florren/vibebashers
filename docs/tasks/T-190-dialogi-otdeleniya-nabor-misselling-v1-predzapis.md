# T-190 — Диалоги отделения, набор misselling_v1, предзаписанные WAV с эталонами

| Поле | Значение |
|---|---|
| Эпик | E16 Аудиомониторинг отделения и мисселлинг [BRD] |
| Субагент | `SA-Signals` (тексты и предыстория сигналов) |
| Оценка | M (1–2 дня) |
| Волна | 2 |
| Слой | `L2` Симулятор и данные (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | нет — можно отложить |
| Статус | `todo` |

## Цель
Корпус 40+ диалогов «сотрудник–клиент» с ролями и таймкодами, 150 размеченных реплик и 10 аудиофайлов с эталонными транскриптами (ТЗ 14.3, 15 SA-Dialogs).

## Разделы ТЗ (docs/TZ.md)
§14.3, §15, §22.4

## Контракты
- `db/schema.sql: bench_datasets, bench_cases, demo_assets`
- `events/compliance/misselling_verdict.schema.json`

## Зависимости
- Зависит от: [T-184](T-184-taksonomiya-missellinga-i-rule-detektor-predvari.md), [T-021](T-021-zolotoj-nabor-benchmarka-golden-v1-i-lite-v1.md)
- Блокирует: [T-191](T-191-benchmark-detektora-missellinga-i-stt-ranner-met.md), [T-192](T-192-scenarij-9-misselling-v-otdelenii-yaml-avtotest.md), [T-219](T-219-korpusa-dtz-transcripts-v1-20-transkriptov-json.md)

## Что сделать
1. data/corpus/dialogs/*.yaml: чистые продажи, 1–2 нарушения, 3+ нарушений; продукты ИСЖ/НСЖ/ПДС/страховка к кредиту/кредитная карта; реплики клиента для контекста.
2. misselling_v1: 150 реплик сотрудника (90 с нарушениями по категориям, 60 чистых продающих) → метрики precision/recall/F1 по категориям и латентность на реплику.
3. data/audio/scenario9_*.wav (16 кГц, моно и стерео) — записи участников команды с согласия или Vosk TTS; *.ref.json с ролями и таймкодами; stt_v1 (10 файлов) для WER; demo_assets с checksum.
4. Тест no-PII (нет реальных имён сотрудников/клиентов).

## Критерии приёмки
- [ ] Набор misselling_v1 прогоняется раннером; аудио проигрывается в STT-конвейер и даёт WER-отчёт.
- [ ] Суммарный размер аудио ≤ 30 МБ.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/unit/test_dialog_corpus.py
python scripts/stt_bench.py --dataset stt_v1
```

## Отчёт субагента
Ветка main, коммит B21 (только тексты/данные). `data/misselling_patterns.yaml`: 8 паттернов двух семейств (misselling: tie_in, substitution, concealment, pressure*, guarantee*; conduct: rudeness, script_violation, misinformation) с examples/counter_examples/keywords, alert_policy (immediate 0.8 / counter / report), recommendation_ru, training_module; * — неактивны по умолчанию. `data/service_scripts.yaml`: retail_service_v1 и contact_center_v1 (этапы с маркерами, запрещённые фразы). Сид — `refs.py::seed_abs_rules`. Детектор/LLM-часть — в карточках L3. Время: ~20 мин.
