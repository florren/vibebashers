# T-021 — Золотой набор бенчмарка golden_v1 и lite_v1

| Поле | Значение |
|---|---|
| Эпик | E2 Справочники и генераторы данных |
| Субагент | `SA-Refs` (справочники) |
| Оценка | M (1–2 дня) |
| Волна | 2 |
| Слой | `L1` Базис (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `in_progress` |

## Цель
Размеченные кейсы для сравнения LLM (ТЗ 14.2).

## Разделы ТЗ (docs/TZ.md)
§14.2, §14.3

## Контракты
- `db/schema.sql: bench_datasets, bench_cases`

## Зависимости
- Зависит от: [T-019](T-019-biblioteka-tekstov-signalov.md)
- Блокирует: [T-060](T-060-uzel-classify-i-prompty-v1.md), [T-129](T-129-benchmark-ranner-i-metriki.md), [T-178](T-178-korpus-publichnyh-otzyvov-i-nabor-reviews-v1.md), [T-190](T-190-dialogi-otdeleniya-nabor-misselling-v1-predzapis.md)

## Что сделать
1. data/golden/golden_v1.jsonl: ≥ 150 кейсов с gold (тип, продукт, система, критичность, сложность, команда, флаги, needs_hitl), сбалансированных по типам и каналам; ≥ 30 % сложных (сарказм, многотемность, неявный продукт).
2. data/golden/lite_v1.jsonl: 30–40 кейсов — подмножество для gate при смене промпта.
3. Разметка проверена вторым проходом (другой субагент/техлид), спорные случаи помечены тегом ambiguous и исключены из accuracy.
4. Загрузчик scripts/seed/bench.py.

## Критерии приёмки
- [x] Наборы валидны по JSON, загружаются; у каждого кейса полный gold.
- [x] Разметка согласована ≥ 95 % при перекрёстной проверке.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
python scripts/seed/bench.py --check
```

## Отчёт субагента
Реализован reviewed corpus v4: golden 200/lite 40, все 8 gold fields, по 20 кейсов
на 10 типов и 16–17 на 12 каналов;64/200 (32%) содержательно сложных текстов.
Lite — exact strict subset, по 4 кейса на тип. Независимый полный case-level
pass: 197/200 = 98.5%; три замечания исправлены и отдельно приняты, затем отдельно
подтверждена единственная provenance-правка human_reason→needs_human.
Исходное согласие не пересчитывается в 100%. Полный отчёт и SHA находятся в
[review](../reviews/README-T-021.md), deployable копия — data/golden/review_v1.json.
Источник routing/policies — main 3c1c12c; финансовые/HITL правила не менялись.

Общий loader проверяет строгий JSON, контрактные enum, полный gold, bool/flags,
баланс, hard coverage, subset, compatibility mirrors и целостность независимого
review. Legacy partial-gold наборы других семейств сохранены. Ambiguous tags
проходят file/DB runner и exports, исключаются из accuracy/critical recall,
сохраняются в latency/cost/JSON/stability; в lite запрещены.

Обычный seed идемпотентен и явно отказывается заменять несовпадающий старый
набор. Поддержан отдельный read-only --plan и явный --apply --plan-sha:
transaction+dataset locks, archival legacy code/provenance, новые canonical IDs,
старые cases/results/IDs неизменны. Active bench/collision/stale plan дают abort;
обе семьи атомарны. Операторский путь и recovery — data/golden/README.md.
Проверки DB выполняются исключительно в собственной scratch cx_t021_golden,
не в primary/prod; реальных LLM/внешних вызовов и новых dependencies нет.

Локальная проверка: backend unit 825 passed/18 skipped после merge main 4a01734; frontend 144 passed,
eslint/tsc, backend ruff/format 323 files и mypy 243 files green. Структурный --check,
contracts 44 schemas/161 paths и drift 191/191 green; license gate 526 distributions green. Новый backend validator:
stdlib trace 90% строк (без добавления coverage dependency). DB acceptance 16 tests
включают actual CLI plan/apply/retry, историю, rollback и ambiguous runner.
Полный monolithic make test и remote CI остаются финальным gate основного агента;
поэтому третий критерий и общий статус пока не отмечены done.

Remote CI:contracts/db подтвердили текущий corpus; owners потребовал явную cross-layer метку для уже согласованных межслойных правок. Заголовок PR #163 дополнен меткой, проверки не менялись; повторный CI обязателен.
