# T-184 — Таксономия мисселлинга и rule-детектор (предварительная отметка)

| Поле | Значение |
|---|---|
| Эпик | E16 Аудиомониторинг отделения и мисселлинг [BRD] |
| Субагент | `SA-Compliance` (аудиосессии, детектор мисселлинга, алерты [BRD]) |
| Оценка | S (≤ 0,5 дня) |
| Волна | 2 |
| Слой | `L3` Агент и контуры (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `done` |

## Цель
Справочник паттернов с примерами, контрпримерами и ключевыми словами; быстрый детектор правил ≤ 300 мс как первый этап гибрида (ТЗ 22.4).

## Разделы ТЗ (docs/TZ.md)
§22.4, §15 (SA-Dialogs)

## Контракты
- `db/schema.sql: misselling_patterns, compliance_triggers`
- `events/common.schema.json: misselling_pattern`
- `api/openapi.yaml: compliance/patterns`

## Зависимости
- Зависит от: [T-005](T-005-primenenie-schema-sql-sqlalchemy-modeli-sessii.md), [T-013](T-013-produkty-sistemy-komandy-kanaly.md)
- Блокирует: [T-185](T-185-llm-detektor-missellinga-lightning-podtverzhdeni.md), [T-190](T-190-dialogi-otdeleniya-nabor-misselling-v1-predzapis.md), [T-215](T-215-taksonomiya-krasnyh-fraz-semejstvo-conduct-ruden.md)

## Что сделать
1. data/misselling_patterns.yaml: tie_in, substitution, concealment (активны), pressure, guarantee (выключены) — name_ru/en, описание, ≥ 8 примеров и ≥ 4 контрпримера, ключевые фразы с весами.
2. app/compliance/rules_detector.py: нормализация текста (ё, регистр, числительные), совпадение фраз и шаблонов с весами → {pattern_code, confidence, quote}; порог предварительной отметки 0,5; ≤ 300 мс.
3. GET/PUT /api/compliance/patterns и вкладка настроек; изменения применяются без рестарта.
4. Тесты на примерах/контрпримерах: контрпримеры не дают отметку ≥ 0,85.

## Критерии приёмки
- [ ] Все примеры из YAML детектируются правилами, контрпримеры — нет (на пороге 0,85).
- [ ] Латентность ≤ 300 мс на реплику.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/unit/test_misselling_rules.py
```

## Отчёт субагента
- `backend/app/compliance/taxonomy.py` (паттерны/скрипты из БД, кэш 30 с, инвалидация по PUT) и `rules_detector.py`: ключевые слова + примеры с нечётким совпадением по основам слов (`phrase_matches`), словарь грубости, запрещённые фразы скрипта, слабые ключи («комиссий нет») не срабатывают в одиночку, смягчающие формулировки гасят guarantee/pressure. `check_script` с учётом отрицания маркеров («паспорт не нужен»). API `GET/PUT /api/compliance/patterns`, `GET /api/compliance/scripts`. Корпус 20/20 (`tests/compliance/test_corpus.py`).
