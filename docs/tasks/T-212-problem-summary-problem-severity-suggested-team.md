# T-212 — problem_summary {problem, severity, suggested_team}: structured output, валидация ≤ 2 предложений, отображение severity ↔ criticality, набор summary_v1

| Поле | Значение |
|---|---|
| Эпик | E18 Приём транскриптов, роутер-инструменты, «красные фразы», зоны карты [ДТЗ] |
| Субагент | `SA-Prompts` (промпты и классификатор) |
| Оценка | S (≤ 0,5 дня) |
| Волна | 3 |
| Слой | `L3` Агент и контуры (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `done` |

## Цель
Классификация отдаёт саммари проблемы ровно в полях ДТЗ и согласует его с внутренней моделью (ДТЗ FR-2.3, ТЗ 7, решение 20.6 п. 29, критерий 29).

## Разделы ТЗ (docs/TZ.md)
§7, §8.1, §14.3, §19

## Контракты
- `events/agent/classification.schema.json: problem_summary`
- `db/schema.sql: incidents.problem_summary`
- `api/openapi.yaml: ProblemSummary, IncidentBrief.problem_summary`

## Зависимости
- Зависит от: [T-060](T-060-uzel-classify-i-prompty-v1.md), [T-210](T-210-trehklassnaya-tonalnost-sentiment-prompt-soglaso.md)
- Блокирует: [T-213](T-213-router-instrumenty-route-to-department-notify-cu.md)

## Что сделать
1. Промпт classify v1.1: блок problem_summary; правило severity=critical (criticality=high + regulator_threat | fraud > 50 000 ₽ | mass_impact | churn_threat для vip/ultra_vip) → needs_human.
2. Валидатор числа предложений (разбиение по .!? с учётом сокращений «руб.», «т. е.»); при нарушении — один ретрай с указанием ошибки, затем усечение до двух предложений.
3. suggested_team сверяется с маршрутом decide; расхождение → запись в compare «ИИ против правил» (T-067) и бейдж в карточке.
4. incidents.problem_summary копируется при создании инцидента; набор data/bench/summary_v1.jsonl (60) с эталонами severity/suggested_team.

## Критерии приёмки
- [ ] ≥ 95 % саммари ≤ 2 предложений на summary_v1; severity (±1) и suggested_team совпадают с эталоном в ≥ 80 %.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
make bench SET=summary_v1
pytest backend/tests/unit/test_problem_summary.py
```

## Отчёт субагента
Ветка `feat/b04-agent`. problem_summary {problem ≤2 предложений ≤300 символов (валидатор в коде: обрезка, маскирование ПДн), severity (critical только при основаниях: regulator_threat/legal/массовость/крупный fraud/churn у VIP, иначе понижается до high; и наоборот повышается), suggested_team (из справочника teams, иначе — по routing_rules)} заполняется в classify и пишется в incidents.problem_summary; выдаётся в IncidentBrief/Signal. Время: ~15 мин.
