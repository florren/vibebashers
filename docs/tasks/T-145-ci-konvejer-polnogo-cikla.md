# T-145 — CI-конвейер полного цикла

| Поле | Значение |
|---|---|
| Эпик | E11 Сценарии и тесты |
| Субагент | `SA-QA` (тесты и CI) |
| Оценка | S (≤ 0,5 дня) |
| Волна | 5 |
| Слой | `L5` Качество (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | нет — можно отложить |
| Статус | `in_progress` |

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
Ветка `codex/T-145-ci-shards`, база T-152 `c6d0485`; cross-layer согласован
в рамках общей ревизии. Jobs contracts/db/tests сохранены; tests — `always()`
aggregate с явным отказом при failed/cancelled/skipped prerequisite; owners
обязателен на PR, intentional skipped owners разрешён только вне PR. Полный pytest
разделён по реально собранным модулям между четырьмя отдельными checkout/PG16;
четыре manifests подтверждают общую revision/collection, exit code и JUnit count.
Добавлены frozen Python installs, lint/frontend jobs, настоящий Docker build,
изолированный real-image Playwright smoke, scheduled nightly slow/perf.
Лицензионный gate T-152 сохранён, mirror.yml не изменён.

Docker helper использует отдельный `:ci` image, случайный project, временные копии
bind mounts и loopback port; `.env` создаётся исключительно через O_EXCL, чужие
файлы/симлинки не трогаются. Копии вложенных mount parents создаются до Docker,
cleanup ограничен своим project. В real-image APP_ENV=dev включает simulator,
LLM_CHAIN/LLM_PROVIDER принудительно mock, API credentials отсутствуют.

Проверки: full standalone four-shard proof на commit `6f87f62` — 1070 passed,
24 skipped, wall 526.648s. Shard times 454.37/178.80/521.73/374.40s;
aggregate union PASS, отсутствие одного manifest намеренно проверено как failure.
Последующие регрессии helper/workflow/owners — 43 passed; staged cross-layer
изменение теперь обнаруживается check_owners, разрешение --allow-cross не ослаблено.
`make lint`, frontend build, E2E TypeScript, contracts, i18n, licenses-check
(526 distributions) прошли. Модельный split сохраняет все 58 Playwright cases:
проверенные read-only/mock files parallel4, settings/new files serial1 после них.

Nightly snapshot на отдельном candidate: demo/5000 seed 14.663s,
simulator.running=true, p95 health6.116/state2.363/signals14.901/map15.291/
dashboard18.594ms, violations=[]; raw samples сохранены в performance artifact.
Это не замена длительного T-144 замера WS/CPU/RAM на целевой машине.
Замер выполнен до нового T-017 operation volume; после его интеграции nightly
нужно повторить на увеличенном фактическом наборе операций.

Открытая граница: real browser smoke обнаружил map containment overflow
(1024×768 SVG bottom772.734375, также 1280 ru). Строгие assertions сохранены;
отдельное исправление делает UI агент. Полный GitHub PR cycle ≤15min требует
замера run после публикации родительским агентом, локальная wall-time shards
не доказывает remote latency. Monolithic `make test` повторно не запускался:
вместо него проверена полная pytest collection через четыре изолированных shards
и отдельно frontend suite; CI повторит это на чистых runners.
Подробности эксплуатации — `docs/CI.md`.
