# CX Pulse Control — цели зафиксированы в AGENTS.md §4. Python-окружение: uv (backend/.venv).
.PHONY: dev dev-front install-front build-front lint-front test test-front test-compliance test-scenarios e2e test-unit test-integration lint fmt sync-contracts contracts-check check-contracts check-owners tasks \
        scenario bench i18n-check cassettes-record stt-bench demo-offline import-transcripts import-csi migrate seed install-backend

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
	cd frontend && npm run lint && npm run typecheck && npm test -- --run

migrate:                    ## alembic upgrade head (DATABASE_URL из .env/окружения)
	cd backend && .venv/bin/alembic upgrade head

seed:                       ## сид по профилю PROFILE=lite|demo|stress (E2, T-011…T-016)
	$(PY) scripts/seed/run.py --profile $(or $(PROFILE),lite)

test: contracts-check test-unit test-integration test-scenarios test-compliance test-front   ## все backend- и frontend-тесты

test-front:
	cd frontend && npm test -- --run

test-compliance:             ## тесты корпуса и детектора (нужна DATABASE_URL_TEST)
	cd backend && .venv/bin/pytest -q tests/compliance

test-unit:
	cd backend && .venv/bin/pytest -q tests/unit

test-integration:           ## нужна DATABASE_URL_TEST; без неё — skip
	cd backend && .venv/bin/pytest -q tests/integration

lint: lint-front
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

i18n-check:                 ## ключи словарей frontend/src/shared/i18n/ru.json и en.json без пустых значений + типы TS в синхроне с OpenAPI
	$(PY) scripts/i18n_check.py
	cd frontend && npm run -s gen:types && git diff --exit-code -- src/shared/api/types.ts

scenario:                   ## прогон демо-сценариев на работающем стенде: make scenario ID=2 (или all); CX_BASE_URL, DATABASE_URL
	$(PY) scripts/scenario_check.py $(or $(ID),all) --base $(or $(CX_BASE_URL),http://localhost:8000)

report:                     ## отчёт о качестве → data/reports/quality-<ts>.md/.json (RUN=id — один запуск; CX_BASE_URL — через API стенда)
	$(PY) scripts/quality_report.py $(if $(RUN),--run $(RUN)) $(if $(CX_BASE_URL),--base $(CX_BASE_URL))

test-scenarios:             ## сценарные тесты ТЗ §18 на mock (нужна DATABASE_URL_TEST)
	cd backend && .venv/bin/pytest -q tests/scenarios

e2e:                        ## дымовые Playwright-тесты фронта против стенда (E2E_BASE_URL, по умолчанию :8000); браузер: npx playwright install chromium
	cd frontend && npx playwright test

stt-model:                  ## скачать малую русскую модель Vosk (≈45 МБ) в data/models/stt — для живого распознавания с микрофона
	python3 scripts/stt_model.py

bench:                     ## локальный mock-бенчмарк или прогноз профиля: DATASET=lite_v1 PROFILE=mock
	cd backend && .venv/bin/python -m app.bench.runner --dataset $(or $(DATASET),lite_v1) --profile $(or $(PROFILE),mock) --repeats $(or $(REPEATS),1)

cassettes-record:           ## запись кассет replay для SCENARIO=… (live LLM, T-198)
	@test -n "$(SCENARIO)" || (echo "укажите SCENARIO=id сценария" >&2; exit 1)
	$(PY) scripts/cassettes_record.py $(SCENARIO)

stt-bench:                  ## локальный Vosk: WER и время распознавания WAV (FILE=…, REF=…)
	$(PY) scripts/stt_bench.py $(if $(FILE),--file "$(FILE)") $(if $(REF),--reference "$(REF)")

demo-offline:               ## установка replay/mock + Vosk без сброса существующих данных
	./install.sh --offline

import-transcripts:        ## импорт каталога транскриптов на сервере (CX_BASE_URL=…)
	$(PY) scripts/import_transcripts.py --base "$(or $(CX_BASE_URL),http://localhost:8000)"

import-csi:                 ## ручной CSI JSON/XLSX через API (FILE=…, CX_BASE_URL=…)
	$(PY) scripts/import_csi.py $(or $(FILE),data/import/csi) --base $(or $(CX_BASE_URL),http://localhost:8000)

.PHONY: run-summary
run-summary:                ## явный пересчёт summary завершённого запуска ID=…
	$(PY) scripts/run_summary.py --id $(ID)
