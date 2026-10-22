# CX Pulse Control — vibebashers, хакатон «Синапс»

Платформа контроля клиентского опыта банка: симулятор клиентской базы и событий, ИИ-агент на LangGraph с инструментами маршрутизации и HITL, контуры внешних площадок (Mock-АБС, правила, быстрый путь), контроль качества диалогов сотрудников (транскрипты, «красные фразы»), карта регионов с зонами и экономикой.

## Документы
- `AGENTS.md` — правила для кодирующих агентов (читать первым), `CLAUDE.md`, `.cursor/rules/`.
- `docs/TZ.md` — техническое задание v1.4; `docs/BRD.md`, `docs/TZ-additional.md` — исходные требования; `docs/BRD-merge-analysis.md` — анализ слияния.
- `docs/PLAN-14D.md` — спринт до демо 9 ноября; `docs/TEAM-SPLIT.md` — слои и роли; `docs/WORKFLOW.md` — рабочий цикл `scripts/cx.py`; `docs/REPO-BOOTSTRAP.md` — репозиторий и CI.
- `docs/tasks/` — 150 карточек задач (индекс в `docs/tasks/README.md`).
- `contracts/` — источник истины: `db/schema.sql` + миграции, `api/openapi.yaml`, `events/*.schema.json` (см. `contracts/README.md`).

## Быстрый старт
```bash
cp .env.example .env            # ключи GigaChat (без них — LLM_PROVIDER=mock)
./install.sh --profile lite     # docker compose: PostgreSQL 16, backend (+ собранный фронт), миграции, сид
make test                       # проверки контрактов, backend, frontend
python scripts/cx.py next       # что делать дальше по плану спринта
```

После `install.sh` интерфейс открывается на `http://<хост>:8000` (фронт собирается в образ backend и раздаётся FastAPI с того же порта).

### Разработка без Docker
```bash
make install-backend && make migrate && make seed PROFILE=lite   # нужна локальная PostgreSQL и DATABASE_URL в .env
make dev                        # backend :8000 (LLM_PROVIDER=mock — без ключей)
make install-front && make dev-front   # vite :5173, прокси /api и /ws на :8000
make build-front                # frontend/dist → backend раздаёт его сам на :8000
```
Экраны: `/` рабочее место (сигналы, инциденты, очередь HITL, отложенные, режим жюри), `/incidents/:id` карточка инцидента, `/engine` «под капотом» (прогоны агента, шаги, граф, цепочка решений, живые события).

Рабочий репозиторий — GitHub; зеркало в [GitVerse](https://gitverse.ru/florren/vibebashers) обновляется автоматически (`.github/workflows/mirror.yml`).
