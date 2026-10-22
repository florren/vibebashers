# T-002 — Docker Compose и Dockerfile'ы (postgres, backend, frontend, mailpit, tgbot)

| Поле | Значение |
|---|---|
| Эпик | E1 Каркас, БД, установка |
| Субагент | `SA-Infra` (инфраструктура, установка, realtime) |
| Оценка | M (1–2 дня) |
| Волна | 1 |
| Слой | `L1` Базис (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `todo` |

## Цель
Воспроизводимый запуск на любой Linux-машине без внешних зависимостей, кроме API LLM/Telegram.

## Разделы ТЗ (docs/TZ.md)
§5, §16.1, §16.2

## Контракты
- AGENTS.md §2

## Зависимости
- Зависит от: [T-001](T-001-skelet-repozitoriya-makefile-env-example-pre-com.md)
- Блокирует: [T-003](T-003-install-sh-ustanovka-odnoj-komandoj.md)

## Что сделать
1. docker-compose.yml: postgres:16-alpine (volume, healthcheck), backend (uvicorn, depends_on healthy), frontend (nginx со статикой Vite, проксирует /api и /ws на backend), профили compose `mailpit` и `tgbot`.
2. Многостадийные Dockerfile'ы: backend (python:3.12-slim, uv/pip, non-root), frontend (node:22 build → nginx:alpine), tgbot (python:3.12-slim).
3. Ограничения ресурсов по умолчанию под 4 ядра/8 ГБ; переменные читаются из .env.
4. Образы не тянут ничего из сети при старте (шрифты/карты в образе).

## Критерии приёмки
- [ ] `docker compose up -d` поднимает стек за ≤ 3 мин на холодном кэше; `/api/health` отвечает ok.
- [ ] Профили `--profile mailpit`, `--profile tgbot` включают сервисы опционально.
- [ ] Образы собираются в CI.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
docker compose config
docker compose up -d && curl -f localhost:8080/api/health
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
