# T-003 — install.sh: установка одной командой

| Поле | Значение |
|---|---|
| Эпик | E1 Каркас, БД, установка |
| Субагент | `SA-Infra` (инфраструктура, установка, realtime) |
| Оценка | M (1–2 дня) |
| Волна | 2 |
| Слой | `L1` Базис (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `done` |

## Цель
Скрипт из ТЗ 16.2: проверка Docker, .env, сборка, миграции, сид по профилю, health-check, вывод адреса мастера и QR.

## Разделы ТЗ (docs/TZ.md)
§16.2

## Контракты
- AGENTS.md §4

## Зависимости
- Зависит от: [T-002](T-002-docker-compose-i-dockerfile-y-postgres-backend-f.md), [T-005](T-005-primenenie-schema-sql-sqlalchemy-modeli-sessii.md), [T-016](T-016-generator-klientov-profili-lite-demo-stress.md)
- Блокирует: [T-151](T-151-readme-i-demo-skript.md), [T-197](T-197-install-sh-i-compose-flagi-no-stt-stt-model-reco.md), [T-270](T-270-bezopasnyj-povtornyj-seed-i-pg-dump-v-docker.md)

## Что сделать
1. Флаги: --profile lite|demo|stress, --offline, --reset, --seed N, --no-mailpit, --with-tgbot, --help; идемпотентность.
2. Проверка docker/compose версии, свободного порта, прав; понятные сообщения об ошибках на русском.
3. Генерация APP_SECRET при первом запуске; .env создаётся из .env.example, если отсутствует.
4. После старта: alembic upgrade head, сид (scripts/seed), снимок baseline (`pg_dump -Fc` → data/baseline/<profile>.dump + .sha256, ТЗ 4.6), ожидание health, печать URL мастера и QR в терминале (python qrcode, ASCII).
5. --reset: если снимок baseline для профиля есть и сид совпадает — pg_restore вместо повторной генерации; scripts/run.sh stop|resume|status|reset-baseline вызывает API T-040.
6. Режим --offline выставляет LLM_PROFILE=mock и отключает бота.

## Критерии приёмки
- [ ] Чистая Ubuntu 22.04/24.04 с Docker: `./install.sh --profile lite` завершается успешно ≤ 5 мин, мастер открывается.
- [ ] Повторный запуск без --reset не ломает данные.
- [ ] `./install.sh --offline` работает без интернета (проверка в сети без egress).
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
./install.sh --profile lite
./install.sh --offline --reset
```

## Отчёт субагента
Коммит B01. `install.sh`: флаги `--profile lite|demo|stress`, `--offline` (LLM replay→mock, бот выкл.), `--reset` (down -v), `--seed N`, `--with-mailpit`, `--with-tgbot`, `--help`; проверки docker/compose v2/прав/портов 5432 и 8000; создание `.env` с генерацией APP_SECRET; ожидание `/api/health` до 120 с; сид через `scripts/seed/run.py` (появится в B21 — пока сообщение «сид ещё не реализован»); вывод URL и QR (если установлен qrcode). Отклонения: не проверялось на реальном Docker (в среде разработки Docker недоступен) — требуется прогон владельцем на Linux; `/setup` появится в T-010.

Freeze03.11: actual offline install на own clean PG16/lite прошёл; initial seed
3.9s+baseline1493715bytes,backend/personal healthy. Проверка портов исправлена
по наблюдаемому RED собственного custom project: точные running service и
published port вместо substring cx-pulse.18focused tests; повтор после
существующего first-start ABS backfill сохранил все114table fingerprints.
Первый restart после seed добавляет17891штатных проводок — это явно раскрыто,
не утверждается неизменность до инициализации. Balance mismatches0.
[Review/proof](../reviews/FREEZE-2026-11-03-offline-install.md). Не проверялись
чистая Ubuntu22/24 VM и сеть с физически запрещённым egress; эти исходные
критерии не отмечаются автоматически.

06.11 — безопасность явного reset: подготовка Vosk, проверка resolved Compose
config и держателей его управляемых томов, сборка и получение только
отсутствующих образов перенесены перед `down -v`. Stopped foreign/one-off
контейнеры явно блокируют reset и автоматически не удаляются. После preflight
запуск использует `--no-build --pull never`; cached images не обновляются.
Новые 11 shell-регрессий: RED10 на прежнем installer и RED1 для `.env` profile → GREEN29 вместе
с соседними installer tests; Ruff и `bash -n` PASS. Полные проверки этого
пакета на момент подготовки отчёта ещё не запускались. Настоящий reset
и primary для проверки не использовались.
[Разбор и ограничения](../reviews/install-reset-preflight.md).

Итоговый isolated gate на `76edc49e45455aca0f62e6fa5a537ee14f209188`: `make lint`, contracts, owners PASS; полный `make test` **4155 passed/20 skipped**. Tracked source после прогона неизменён, собственный PG остановлен. Native preflight-only на собственном scratch Compose project проверил `.env` profile, cached images без pull и сохранённый stopped/created one-off holder; реального reset и primary-операций не было. Финальное уточнение комментария не меняет Python AST; exact-head CI требуется перед merge.

06.11 — дополнительная lifecycle-регрессия первого seed: backend загружал пустой pointer до seed, после создания baseline память оставалась `None`. Установщик теперь сравнивает API/PG readonly и только для initial quiet baseline выполняет backend restart (grace120s), bounded health120s и повторное сравнение. Same-pointer, включая активный World, не перезапускается; остальные mismatch и ошибки не объявляют установку успешной. Engine stale guards не менялись. RED7/1 → targeted51PASS; native PG1PASS15.66s (old/new native memory, настоящий seed, Start и ticks, сохранённый банк/часы/RNG до Start). Собственный PG остановлен, primary/Live LLM/TG не использованы. Полный gate запускается после source freeze. [Review](../reviews/install-post-seed-reload.md).

06.11 — cached `--restart`: отдельный ранний путь без build/pull/seed/Vosk/Tuna/записи `.env`; несовместим с установочными флагами. До действий проверяются3existing regular containers и локальные image IDs. Running PG сохраняется, stopped PG startsameID и проходит health; затем backend/personal restart exactIDs. Нет создания/удаления ресурсов или reset fallback. Прежние recovery guards и явный Resume для interrupted сохранены. Build failure даёт путь приватного0600лога и команду cachedrestart. Targeted15PASS и neighbors66PASS7.03s; native V5PASS (реальные Compose/PG, syntheticHTTP, unchangedPGStartedAt/IDs/images/storage), ownfixtures archived/cleaned безvolumes/primary. Ruff/mypy/bashPASS; combinedfullgate публикуется в PR. [Review](../reviews/install-cached-restart.md).

В native image smoke проверен настоящий startup и Start/Pause/Stop. Причинная проверка shutdown выявила shell PID1: без `exec` backend завершался exit137 после30с; с единственным CMD override `exec uvicorn` — PID1 uvicorn, exit0 за1,359с, все shutdown markers. Dockerfile сохраняет миграции и передаёт процесс серверу через `exec`. API/DDL/формулы не менялись; primary и провайдеры не использованы. Полный backend набор выполняется четырьмя изолированными CI runners с проверкой полной коллекции; частичный последовательный запуск отменён и не объявляется PASS.
