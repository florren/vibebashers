# T-130 — UI бенчмарков

| Поле | Значение |
|---|---|
| Эпик | E10 Бенчмарки и экономика |
| Субагент | `SA-Bench` (бенчмарки) |
| Оценка | M (1–2 дня) |
| Волна | 4 |
| Слой | `L3` Агент и контуры (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | нет — можно отложить |
| Статус | `todo` |

## Цель
Экран сравнения: таблица профилей × метрик, графики, детали по кейсам, запуск с прогнозом.

## Разделы ТЗ (docs/TZ.md)
§14.3, §12.2

## Контракты
- `api/openapi.yaml: bench/*`

## Зависимости
- Зависит от: [T-129](T-129-benchmark-ranner-i-metriki.md), [T-007](T-007-karkas-frontend-vite-ts-strict-tailwind-tokeny-t.md)
- Блокирует: [T-154](T-154-materialy-zaschity-tezisy-slajdy-opory-otvety-na.md), [T-156](T-156-polnye-slovari-ru-en-i-proverka-i18n.md), [T-191](T-191-benchmark-detektora-missellinga-i-stt-ranner-met.md)

## Что сделать
1. Таблица сравнения с сортировкой и подсветкой лучшего; радар/столбцы ECharts; прогресс прогонов через WS bench/*; детали кейса (текст, gold, предсказание, ошибки); кнопка запуска с выбором набора/профилей/повторов и прогнозом; индикаторы лимитов и баланса OpenRouter.

## Критерии приёмки
- [ ] Сравнение Ultra/Lightning/Pro/3 OpenRouter/mock отображается на одном экране.
- [ ] Прогноз показывает предупреждение при нехватке лимита.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
npx playwright test e2e/bench.spec.ts
```

## Отчёт субагента
Ветка: `feat/T-130-bench-ui` (от main `542d6f1`). PR нет.

Экран `/engine`, вкладка bench, ходит в живой API `bench/*`: datasets, runs, прогон по id, sentiment, экспорт csv/json. POST раннера всё ещё mock на один прогон — UI его не переписывает.

Чужие пути L4: `frontend/package.json`, `frontend/package-lock.json`, `frontend/src/pages/engine/BenchTab.tsx`, `frontend/src/pages/engine/EnginePage.tsx`, `frontend/src/shared/ws/client.ts`, `frontend/src/shared/i18n/ru.json`, `frontend/src/shared/i18n/en.json`, `frontend/src/test/bench.test.tsx`.

Лицензия echarts 5.5.1: Apache-2.0. Контракты не менялись. `docs/LICENSES.md` не создавался (файла нет, T-152).


Дополнение: `feat/T-130-bench-ui-followup`, от main `c238051` после PR #66; источник альтернативы — `wip/T-130-benchtab-alt` (`228f222`).
- `BenchTab.tsx`: выборочно перенесены фильтрация выбранных ID по активным профилям и переключение направления сортировки; начальное направление остаётся «лучшее первым», отсутствующие метрики остаются в конце, подсветка лучшего результата не зависит от направления. `aria-sort` отражает направление. Компонент целиком не заменялся.
- `bench.test.tsx`: адаптированы проверки разрешённого старта и перехода из EnginePage; добавлены regression-тесты деактивации профилей и сортировки в обе стороны. До исправления два новых теста падали.
- `client.ts`/`hooks.ts`: поведенческих дополнений не найдено, перенос не нужен. Словари WIP не использовались; новых строк UI нет. Package/lockfile сохранены из main (в WIP остались прежние @fontsource, удалённые в #66); EnginePage уже содержал вкладку.
- Раннер, контракты, миграции и следующие карточки не менялись. Локально (Node 22): npm lint, tsc --noEmit, vitest **33 passed**, build и генерация типов без diff; i18n **1032 ключа**; contracts, OpenAPI drift и owners --allow-cross зелёные. Итоговый CI и merge — в PR follow-up.
