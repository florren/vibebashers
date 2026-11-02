# T-019 — Библиотека текстов сигналов

| Поле | Значение |
|---|---|
| Эпик | E2 Справочники и генераторы данных |
| Субагент | `SA-Signals` (тексты и предыстория сигналов) |
| Оценка | L (3–4 дня) |
| Волна | 2 |
| Слой | `L2` Симулятор и данные (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `in_progress` |

## Цель
Разнообразные реалистичные обращения: тип × продукт × канал × тон × психотип, включая сарказм, сленг, опечатки, транскрипты звонков.

## Разделы ТЗ (docs/TZ.md)
§3.6, §4.4, §7, §12.5

## Контракты
- `events/sim/signal.schema.json`
- `events/common.schema.json`

## Зависимости
- Зависит от: [T-012](T-012-segmenty-psihotipy-doli-psihotipov-po-segmentam.md), [T-013](T-013-produkty-sistemy-komandy-kanaly.md), [T-014](T-014-kody-oshibok-tipy-signalov-pravila-marshrutizaci.md)
- Блокирует: [T-020](T-020-predystoriya-signalov-incidentov-statusov-artefa.md), [T-021](T-021-zolotoj-nabor-benchmarka-golden-v1-i-lite-v1.md), [T-022](T-022-testy-dannyh-no-pii-pokrytie-idempotentnost-proi.md), [T-178](T-178-korpus-publichnyh-otzyvov-i-nabor-reviews-v1.md), [T-240](T-240-korpus-product-lines-v1-i-istoriya-teksty-po-15.md)

## Что сделать
1. data/signal_templates/*.yaml: ≥ 400 шаблонов с плейсхолдерами (сумма, продукт, дата, промо, город), раскладка по 10 типам × 4 продуктам × 8 каналам; ≥ 25 % с сарказмом/иронией/сленгом/опечатками; транскрипты звонков с ремарками оператора; письма с темой; соцсети с хэштегами/эмодзи.
2. Генератор текста: выбор шаблона по типу/психотипу/тону, вариативность (синонимы, порядок предложений, опечатки по вероятности), ru/en (en ≈ 5 %).
3. generator_hint с истинными метками для тестов и бенчмарков.
4. Пул «шумовых» сообщений (спам, не о банке) ≈ 3 %.

## Критерии приёмки
- [ ] Mock-классификатор по правилам даёт accuracy_type ≤ 0.75 на выборке «сложных» шаблонов (чтобы разница с LLM была видна).
- [ ] Нет реальных брендов/имён (тест).
- [ ] Покрытие: каждая комбинация тип × продукт × канал имеет ≥ 3 шаблона.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/unit/test_signal_templates.py
```

## Отчёт субагента
Ветка `codex/T-019-signal-corpus`, отдельный worktree. Исходная грамматика
`data/signal_templates/catalog.yaml` даёт 2880 уникальных развёрнутых текстов
(60 смысловых вариантов × продукты × каналы). По каждой комбинации есть ≥3 ru;
50% ru-шаблонов сложные. Добавлены форматы каналов, seeded en≈5%, отдельный
небанковский noise pool, gold/template_id. Сид сохраняет все480 ячеек и даёт
3% noise без ложных банковских меток; runtime передаёт выбранный канал.
Старый интерфейс без channel, независимый golden corpus и replay inputs сохранены.
Контракты/DDL/денежные и HITL политики не меняются. Применение к рабочей БД не выполнялось.

Проверки на исходном пакете: 977 unit passed/18skip; 34 targeted unit/PG passed
за11.60s (реальный seed, coverage, повтор без изменения текста/меток). Full lint
до последней коррекции форматирования письма прошёл:144frontend,ruff/mypy245,drift191.
Mock accuracy_type=0.15 на960 сложных ru-примерах; classifier не менялся и gold не получал.
Первый PG запуск выявил ошибку стилизации заголовка письма — исправлена и покрыта
всеми пятью стилями. Ошибки тестового URL/autocommit и параллельного schema generator
исправлены в запуске/новом тесте; assertions существующих тестов не ослаблялись.

Итоговый full после main-composition/coverage и CI ещё предстоит; live GigaChat
не вызывался, карточка не закрывается. Описание библиотеки и точного способа подсчёта:
`data/signal_templates/README.md`. Логи `/tmp/t019-{targeted,pg-targeted,full-unit,lint}.log`.

Уточнение границы хранения: gold находится в `signals.meta.generator_hint`, а не
в public classification; шум имеет classification=null. Язык ru/en сохраняется
в signals.lang и для seed, и для runtime. Actual read API проверен без lifespan:
1PG/API passed7.24s, meta/gold не публикуются. Ещё34 targeted unit/PG passed12.73s.
Composed unit1145/18 прошли до этого уточнения, полный интеграционный run остановлен
для исправления найденной границы; завершённым не объявляется. Чистые corpus/textgen
модули:100%44/44 и97%101/104 coverage; это не покрытие всех изменённых seed/runtimeстрок.
Существующая частичная historical classification — отдельный пробел T020: этот пакет
не выдаёт её за полный валидированный результат Mock-графа.

Финальные фазы проверки:1145unit/18skip +269integration/4skip и единственный
исправленный CSV fixture test→1passed6.36s; scenarios43/2skip,compliance31,
frontend163. После последней параметризации sums/days/promo29corpus unit passed;
ещё30targetedunit/PG подcoverage (с дочерним seed и реальнымWorld) passed40.09s.
Это последовательные фазы/targeted reruns, не один повторный монолитныйfullrun.
Added executable Python coverage82/82=100% относительноT018424cf2e.
Finaldemo5000 на96caa2a:21.502s includingdump,4CPU/PG2GB,600000operations,
2500signals,75noise,118en,0langmismatch,480/480coverage,31.8%hardtext;
proof docs/reviews/T-019-demo-seed-proof.json. Originalbenchmark24.813s/a9fdedd
относился к предыдущим трём строкам текста; финальная новая версия измерена отдельно.
Текущий exact-head CI остаётся gate; карточка in_progress.
