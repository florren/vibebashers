# T-145 — CI-конвейер полного цикла

| Поле | Значение |
|---|---|
| Эпик | E11 Сценарии и тесты |
| Субагент | `SA-QA` (тесты и CI) |
| Оценка | S (≤ 0,5 дня) |
| Волна | 5 |
| Слой | `L5` Качество (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | нет — можно отложить |
| Статус | `review` |

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

Real-image smoke выявил map containment overflow (1024×768 и 1280 ru).
Исправление UI агента `ad99a099` включено cherry-pick `4a088b6`: карта получает
реальную высоту рабочей области, mobile сохраняет aspect ratio. Строгие layout
assertions сохранены. Final image build PASS; единый полный Playwright запуск
58 passed за 2.5min, включая 20 map cases. Screenshot 1024×768 просмотрен: SVG/легенда
в viewport, карта читаема. Trace fixture /api/scenarios актуализирована, smoke
темы проверяет actual combobox и server persistence; screenshots идут в artifacts,
tracked PNG больше не перезаписываются. Cleanup своего Compose project/volumes/
network/.env прошёл, рабочая ветка чистая перед отчётным commit.

Открытая граница: полный GitHub PR cycle ≤15min требует
замера run после публикации родительским агентом, локальная wall-time shards
не доказывает remote latency. Monolithic `make test` повторно не запускался:
вместо него проверена полная pytest collection через четыре изолированных shards
и отдельно frontend suite; CI повторит это на чистых runners.
Подробности эксплуатации — `docs/CI.md`.


CI follow-up PR #155: run 41343187290 выявил race между незавершённым
`route.fetch('/api/settings')` и ручным `context.close()` в map-layout.
Layout assertions были корректны. Interception карты перенесён на context,
cleanup всегда снимает routes через `unrouteAll({behavior: 'wait'})`, проверяет
нулевое число активных callbacks и только затем закрывает context. Такой же
drain применён к mobile route.fetch. Ошибки не подавляются, retries и пороги
не менялись. API проверен по установленным Playwright types.

Проверка follow-up на одном изолированном real-image candidate: 100/100 map
cases (20 × 5 повторов) за 40.4s; затем полный suite 58/58 за 2.3min.
E2E TypeScript и collection 58 cases проходят; cleanup project/volumes/network/
.env завершился успешно. Логи `/tmp/t145-map-repeat100.log` и
`/tmp/t145-lifecycle-image58.log`. Parent выполняет push и повтор GitHub CI.


Удалённое подтверждение: PR #155, head517324e, GitHub run41345164835
(https://github.com/florren/vibebashers/actions/runs/41345164835) завершился success.
created_at/run_started_at20:07:01Z, updated_at20:15:53Z01.11.2026: полный цикл8min52s,
включая contracts/db/owners/lint,4backend shards,frontend,imagebuild иe2e.
Порог≤15min подтверждён этим запуском. После обновления базы T152/T014 выполняется
новый цикл; закрытие карточки по остальному DoD не заявлено. Прежняя открытая
граница remote latency выше относится к состоянию до публикации этого run.
