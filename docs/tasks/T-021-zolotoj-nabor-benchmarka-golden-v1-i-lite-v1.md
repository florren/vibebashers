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
- [ ] Наборы валидны по JSON, загружаются; у каждого кейса полный gold.
- [ ] Разметка согласована ≥ 95 % при перекрёстной проверке.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
python scripts/seed/bench.py --check
```

## Отчёт субагента
WIP `codex/T-021-golden-datasets`: подготовлен candidate v2 200/40 и строгий
canonical loader. Источники на момент разметки — f594c43; independent review
всех200cases выполняет основной агент. Frozen golden SHA256
4a703aa454566817f6942f55bc9cd09129c5526855052b41da1ae032d6240bb9,
lite SHA25638d29696905378db7ed2f8d0646ddeb712e94b779a48aa9e237b76e70157bbc7.
Initial v1 отозван после замечаний, его partial review не считается agreement.
V2 frozen copy находится в /tmp/t021-review-candidate-v2; её не меняем до полного
review. Найдены stale routes после merge T014 в main; следующим шагом merge main
в эту ветку и точечный v3 с source SHA, неизменными texts и повторной независимой
проверкой изменённых labels. ≥95% и done пока не заявлены.

Код в разработке: единая validation канонических JSONL, exact legacy mirrors,
строгий lite subset, tags через file/DB runner, ambiguous вне accuracy/critical
recall. Структурная проверка --check проходит; полноценные regression/unit/DB
проверки и стратегия versioned upgrade непустых старых DB datasets ещё в работе.
Исторические bench_cases/results не будут перезаписаны или удалены молча.
