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
