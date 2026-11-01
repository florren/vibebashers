# CI полного цикла (T-145)

Обязательные имена ruleset сохранены: `contracts`, `db`, `tests`. Последний job
выполняется с `always()` и явно отвергает `failure`, `cancelled`, `skipped` любого
из contracts/db/lint/backend-tests/frontend-tests/build-images/e2e-smoke.
Проверка владельцев отдельно учитывает commit diff, index, worktree и untracked.

Четыре backend runners имеют отдельные checkout и PostgreSQL 16. Helper
`scripts/ci_test_shard.py` собирает настоящую pytest collection без исключения
маркеров, распределяет целые модули и запускает каждый модуль ровно один раз.
Manifests содержат revision, полную collection nodeids, распределение, exit code
и число JUnit testcases. Aggregate требует четыре успешных manifests с одинаковой
collection/revision и точным объединением всех модулей. Тесты, regenerating models,
не запускаются конкурентно в одном checkout. Frontend проверяется через
`npm run typecheck`, Vitest, production build и drift generated API types;
после build отдельно проверяются локальные font assets. Все Python jobs используют
`uv sync --frozen`; gate лицензий T-152 сохранён.

`build-images` собирает настоящий `backend/Dockerfile` вместе с обоими frontend
bundle и передаёт точный image `cx-pulse-backend:ci` через artifact.
`e2e-smoke` загружает его и запускает `scripts/ci_compose.py`: компилирует текущий
Compose, создаёт случайный `cx-ci-*` project с отдельными volumes/network,
копирует bind sources в temporary directory, публикует только loopback `18080`,
задаёт APP_ENV=dev (test отключает simulator/workers), mock LLM, выполняет lite seed/restart и весь Playwright suite: проверенные read-only/mock files — четыре workers, затем
serial settings phase (один worker, зависит от read-only). Новые файлы по умолчанию
попадают в serial phase.
Рабочий `:latest` не используется. Existing `.env`, включая dangling symlink,
отклоняется; helper удаляет только созданный им inode. `finally` удаляет только
ресурсы собственного Compose project. Не запускать helper в рабочем checkout
стенда: используйте отдельный checkout без `.env`.

Ежедневно в 02:17 UTC и через workflow_dispatch тот же полный backend suite
(включая `slow`, без фильтрации) дополняется nightly image run с demo/5000 clients.
Отчёт `frontend/performance-results/performance.json` сохраняет длительность seed,
состояние активного симулятора, 21 последовательный HTTP sample для пяти endpoints,
nearest-rank p95, max и нарушения порогов seed ≤90s / API p95 ≤300ms. Ошибки API
и превышения сохраняются до падения job. Это короткий snapshot на GitHub runner;
он не заменяет десятиминутную проверку WS/CPU/RAM на целевой машине из T-144.
Artifacts загружаются с `always()` и доступны даже при падении проверок.

Ограничение полного PR-цикла ≤15 минут проверяется по фактическим timestamps
GitHub run после публикации: локальные измерения отдельных shards не доказывают
это время с учётом очереди runners, cold build и передачи image artifact.
