# T-219 — Корпуса ДТЗ: transcripts_v1 (20 транскриптов JSON/TXT с эталонами), red_phrases_v1 (120 реплик), сид service_scripts и mock-ленты

| Поле | Значение |
|---|---|
| Эпик | E18 Приём транскриптов, роутер-инструменты, «красные фразы», зоны карты [ДТЗ] |
| Субагент | `SA-Signals` (тексты и предыстория сигналов) |
| Оценка | M (1–2 дня) |
| Волна | 2 |
| Слой | `L2` Симулятор и данные (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `todo` |

## Цель
Синтетические данные для проверки приёма транскриптов, детектора «красных фраз» и polling-адаптера; без ПДн, с эталонами (ТЗ 14.3, 15).

## Разделы ТЗ (docs/TZ.md)
§14.3, §15, §22.8, §18

## Контракты
- `events/ingest/transcript.schema.json`
- `events/compliance/transcript_report.schema.json`

## Зависимости
- Зависит от: [T-190](T-190-dialogi-otdeleniya-nabor-misselling-v1-predzapis.md), [T-178](T-178-korpus-publichnyh-otzyvov-i-nabor-reviews-v1.md)
- Блокирует: —

## Что сделать
1. data/import/transcripts/: 20 транскриптов (10 JSON + 10 TXT; 12 отделение, 8 контакт-центр), включая scenario10_retail.txt; у каждого эталон в data/bench/transcripts_v1/<id>.expected.json (ожидаемый сигнал клиента, категории находок, этапы скрипта).
2. data/bench/red_phrases_v1.jsonl: по 30 реплик на rudeness / script_violation / misinformation + 30 чистых; для misinformation — эталонный факт и source_table.
3. Сид service_scripts.retail_service_v1; тексты mock-ленты для polling (30 сообщений, включая сценарий 11 с привязкой к клиенту с повторной жалобой).
4. Проверка схем всех файлов в CI (contracts_check расширить на data/import).

## Критерии приёмки
- [ ] Все файлы валидны по схемам; парсер T-208 читает все 20 без ошибок.
- [ ] Нет ПДн (detect-secrets и словарный фильтр).
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
python scripts/contracts_check.py --data
pytest backend/tests/unit/test_corpora_dtz.py
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
