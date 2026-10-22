# CX Pulse Control — цели зафиксированы в AGENTS.md §4. Python-окружение: uv (backend/.venv).
.PHONY: dev dev-front install-front build-front lint-front test test-unit test-integration lint fmt sync-contracts contracts-check check-contracts check-owners tasks \
        scenario bench i18n-check cassettes-record stt-bench demo-offline import-transcripts migrate seed install-backend

UV ?= uv
PY := backend/.venv/bin/python
BACKEND_PY := cd backend && .venv/bin/python

install-backend:            ## создать backend/.venv и поставить зависимости (uv)
	cd backend && $(UV) venv -q -p 3.12 .venv && $(UV) sync -q --frozen

dev:                        ## backend с автоперезагрузкой (нужна локальная PostgreSQL и .env); фронт — make dev-front (vite :5173 → proxy :8000)
	cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000

dev-front:                  ## vite dev-сервер фронта с прокси /api и /ws на :8000
	cd frontend && npm run dev

install-front:              ## npm ci во frontend
	cd frontend && npm ci

build-front:                ## сборка фронта в frontend/dist (backend раздаёт её с :8000)
	cd frontend && npm run build

lint-front:                 ## eslint + tsc + vitest фронта
	cd frontend && npm run lint && npx tsc --noEmit && npm test -- --run

migrate:                    ## alembic upgrade head (DATABASE_URL из .env/окружения)
	cd backend && .venv/bin/alembic upgrade head

seed:                       ## сид по профилю PROFILE=lite|demo|stress (E2, T-011…T-016)
	$(PY) scripts/seed/run.py --profile $(or $(PROFILE),lite)

test: contracts-check test-unit test-integration   ## все проверки

test-unit:
	cd backend && .venv/bin/pytest -q tests/unit

test-integration:           ## нужна DATABASE_URL_TEST; без неё — skip
	cd backend && .venv/bin/pytest -q tests/integration

lint:
	cd backend && .venv/bin/ruff check app tests && .venv/bin/ruff format --check app tests && .venv/bin/mypy app
	$(PY) scripts/check_openapi_drift.py

fmt:
	cd backend && .venv/bin/ruff check --fix app tests && .venv/bin/ruff format app tests

contracts-check check-contracts:
	$(PY) scripts/contracts_check.py

check-owners:
	$(PY) scripts/check_owners.py --base main

tasks:
	$(PY) scripts/gen_tasks.py

sync-contracts:             ## контракты → код: schema.sql, миграции, enums, Pydantic, модели (если DATABASE_URL), TS-типы (если frontend)
	cp contracts/db/schema.sql backend/schema.sql
	mkdir -p backend/migrations backend/alembic/versions && cp contracts/db/migrations/*.sql backend/migrations/ && cp contracts/db/alembic/versions/*.py backend/alembic/versions/
	$(PY) scripts/gen_enums.py
	$(PY) scripts/gen_schemas.py
	$(PY) scripts/gen_api_stubs.py
	$(PY) scripts/gen_models.py
	cd frontend && npm run -s gen:types

i18n-check:                 ## ключи словаря frontend/src/shared/i18n/ru.json без пустых значений + типы TS в синхроне с OpenAPI
	$(PY) scripts/i18n_check.py
	cd frontend && npm run -s gen:types && git diff --exit-code -- src/shared/api/types.ts

scenario bench:
	@echo "цель $@ реализуется в E5/E10/E11/E13 — см. AGENTS.md раздел 4"

cassettes-record stt-bench demo-offline:
	@echo "цель $@ реализуется в E16/E17 (T-181, T-194, T-197, T-198) — см. AGENTS.md раздел 4"

import-transcripts:
	@echo "цель $@ реализуется в E18 (T-208) — POST /api/ingest/transcripts/import"
