# T-145 — CI-конвейер полного цикла

| Поле | Значение |
|---|---|
| Эпик | E11 Сценарии и тесты |
| Субагент | `SA-QA` (тесты и CI) |
| Оценка | S (≤ 0,5 дня) |
| Волна | 5 |
| Слой | `L5` Качество (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | нет — можно отложить |
| Статус | `todo` |

## Цель
Lint → контракты → тесты → сборка → смоук на собранных образах.

## Разделы ТЗ (docs/TZ.md)
§17

## Контракты
- AGENTS.md §4, §8

## Зависимости
- Зависит от: [T-001](T-001-skelet-repozitoriya-makefile-env-example-pre-com.md), [T-141](T-141-testovaya-infrastruktura-backend.md), [T-143](T-143-playwright-smouk-i-vizualnaya-regressiya.md)
- Блокирует: —

## Что сделать
1. Джобы: lint, contracts-check, backend-tests (с PostgreSQL-сервисом), frontend-tests, build-images, e2e-smoke (compose up на раннере, Playwright), nightly slow/perf.

## Критерии приёмки
- [ ] PR не мержится без зелёного CI; время полного цикла ≤ 15 мин.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
gh workflow view ci (или аналог GitVerse)
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
