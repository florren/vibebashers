# T-001 — Скелет репозитория, Makefile, .env.example, pre-commit, CI

| Поле | Значение |
|---|---|
| Эпик | E1 Каркас, БД, установка |
| Субагент | `SA-Infra` (инфраструктура, установка, realtime) |
| Оценка | M (1–2 дня) |
| Волна | 1 |
| Слой | `L1` Базис (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `done` |

## Цель
Единая точка входа для всех субагентов: структура каталогов из AGENTS.md §3, цели make, шаблон окружения, линтеры и CI.

## Разделы ТЗ (docs/TZ.md)
§16.1, §16.3, §17

## Контракты
- AGENTS.md §3–4

## Зависимости
- Зависит от: —
- Блокирует: [T-002](T-002-docker-compose-i-dockerfile-y-postgres-backend-f.md), [T-004](T-004-karkas-fastapi-konfig-logirovanie-oshibki-health.md), [T-005](T-005-primenenie-schema-sql-sqlalchemy-modeli-sessii.md), [T-006](T-006-sync-contracts-generaciya-enums-pydantic-shem-ts.md), [T-007](T-007-karkas-frontend-vite-ts-strict-tailwind-tokeny-t.md), [T-145](T-145-ci-konvejer-polnogo-cikla.md), [T-152](T-152-licenses-md-i-istochniki-dannyh.md), [T-153](T-153-nachalnyj-nabor-adr.md)

## Что сделать
1. Создать каталоги backend/, frontend/, tgbot/, data/, scripts/, docs/, contracts/ (скопировать из пакета контрактов).
2. Makefile с целями dev, test, lint, sync-contracts, contracts-check/check-contracts, check-owners, scenario, bench, i18n-check (пока заглушки с echo там, где эпик ещё не начат). Python-окружение — uv: backend/pyproject.toml + uv.lock (ruff, mypy strict, pytest, pytest-asyncio); pip/poetry не использовать.
3. .env.example: DATABASE_URL, APP_SECRET, GIGACHAT_AUTH_KEY_1/2, GIGACHAT_SCOPE, OPENROUTER_API_KEY, OPENROUTER_BASE_URL, LOCAL_LLM_BASE_URL, TELEGRAM_BOT_TOKEN, MAILPIT_ENABLED, APP_LANG, SIM_SEED — с комментариями на русском.
4. .gitignore: .env и .env.*.local, data/models/stt/vosk-model-ru-0.42/ (большая модель Vosk — только локальная загрузка), data/baseline/*.dump, backend/schema.sql и backend/migrations/ (копии из contracts/), frontend/src/shared/api/types.ts и */contracts/enums.* (генерируются make sync-contracts), node_modules/, .venv/, __pycache__/, dist/, playwright-report/, *.wav вне data/audio/. Малая модель vosk-model-small-ru-0.22 и кассеты data/cassettes/*.jsonl коммитятся (T-181, T-198).
5. pre-commit: ruff (format+lint), mypy, eslint, prettier, check-added-large-files (лимит 60 МБ — чтобы прошла малая модель Vosk, но не большая), detect-secrets.
6. CI: .github/workflows/ci.yml уже в репозитории (job'ы contracts / db / owners / tests работают на пакете контрактов). Усилить, не переименовывая job'ы (они в ruleset main): в tests — uv sync --frozen, ruff, mypy, pytest с PostgreSQL service, npm ci/lint/tsc/vitest/build; в db — alembic upgrade head → downgrade 0002 → upgrade head; добавить scripts/check_openapi_drift.py и scripts/i18n_check.py, на которые CI уже ссылается. mirror.yml не трогать.
7. docs/LICENSES.md с таблицей зависимостей и лицензий (заполняется далее).

## Критерии приёмки
- [ ] `make lint` и `python scripts/contracts_check.py` проходят на чистом клоне.
- [ ] CI зелёный на PR в main.
- [ ] В .env.example нет реальных значений секретов (detect-secrets чист).
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
make lint
python scripts/contracts_check.py
```

## Отчёт субагента
Коммит B01 в `main` (без PR — защита ветки отключена владельцем). Сделано: `backend/pyproject.toml` (uv, Python 3.12, ruff/mypy strict/pytest), `uv.lock`, `Makefile` с реальными целями (dev, test, lint, fmt, migrate, sync-contracts, contracts-check, check-owners), `.env.example` (все переменные ТЗ), `.pre-commit-config.yaml` (ruff, detect-secrets, large files 60 МБ), `backend/Dockerfile`, `docker-compose.yml` (postgres:16 + backend, mailpit по профилю tools). CI: в job `tests` добавлен шаг `check_openapi_drift.py`, имена jobs не менялись. Отклонения: нет frontend — цели TS-типов пропускаются с сообщением; `scripts/i18n_check.py` не создан (T-156). Исполнитель: Perplexity Computer, 22.10.
