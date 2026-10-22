# T-215 — Таксономия «красных фраз»: семейство conduct (rudeness, script_violation, misinformation), политики алерта, service_scripts и проверка фактов по продуктам

| Поле | Значение |
|---|---|
| Эпик | E18 Приём транскриптов, роутер-инструменты, «красные фразы», зоны карты [ДТЗ] |
| Субагент | `SA-Compliance` (аудиосессии, детектор мисселлинга, алерты [BRD]) |
| Оценка | M (1–2 дня) |
| Волна | 3 |
| Слой | `L3` Агент и контуры (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `todo` |

## Цель
Детектор отделения распознаёт грубость, нарушение скрипта и неверную информацию с источником истины из БД и политиками алерта counter / immediate / report (ДТЗ FR-4.2, ТЗ 22.8, решения 20.6 п. 23–24).

## Разделы ТЗ (docs/TZ.md)
§22.4, §22.8, §13, §19, §20.6

## Контракты
- `events/common.schema.json: misselling_pattern, violation_family, alert_policy`
- `events/compliance/misselling_verdict.schema.json: family, recommendation_ru, fact_check`
- `db/schema.sql: misselling_patterns.family/alert_policy/…, compliance_triggers.recommendation_ru/fact_check, service_scripts`
- `api/openapi.yaml: GET /api/compliance/scripts`

## Зависимости
- Зависит от: [T-184](T-184-taksonomiya-missellinga-i-rule-detektor-predvari.md), [T-185](T-185-llm-detektor-missellinga-lightning-podtverzhdeni.md)
- Блокирует: [T-216](T-216-paketnyj-analiz-transkripta-pacing-batch-transcr.md), [T-218](T-218-karta-sloj-zony-zelenaya-zheltaya-krasnaya-po-v.md)

## Что сделать
1. Сид misselling_patterns: три паттерна conduct с family/alert_policy/immediate_threshold/recommendation_ru/training_module; service_scripts.retail_service_v1 (6 этапов с маркерами и запрещёнными формулировками).
2. Rule-детектор: словари грубости и запрещённых формулировок; маркеры этапов скрипта (для batch — проверка последовательности, для realtime — только запрещённые фразы).
3. Проверка фактов: экстракция утверждений о ставках/комиссиях/сроках (LLM structured output) → сервис fact_check сверяет с products/tariffs/economics_settings → truth; verified=true только при точном совпадении продукта; confidence < 0,8 → «требует проверки» без алерта.
4. LLM-детектор (T-185) расширен семейством conduct и полем recommendation_ru; в realtime misinformation проверяется только по продукту сделки (бюджет 2 с).
5. Политики: counter (мисселлинг, порог 3), immediate (rudeness/misinformation ≥ immediate_threshold → алерт kind=immediate сразу), report (без алерта).

## Критерии приёмки
- [ ] На red_phrases_v1 F1 по conduct ≥ 0,75; для каждого misinformation есть fact_check с truth из БД.
- [ ] Грубость с уверенностью 0,9 даёт алерт immediate без ожидания счётчика.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
make bench SET=red_phrases_v1
pytest backend/tests/unit/test_conduct_detector.py backend/tests/unit/test_fact_check.py
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
