# Минимальный Makefile-скелет; цели реализуются в эпике E1 (SA-Infra) и E15–E17 (v1.3). Имена целей зафиксированы в AGENTS.md.
.PHONY: check-contracts check-owners dev test lint sync-contracts contracts-check tasks scenario bench i18n-check cassettes-record stt-bench demo-offline import-transcripts

contracts-check check-contracts:
	python scripts/contracts_check.py

check-owners:
	python scripts/check_owners.py --base main

tasks:
	python scripts/gen_tasks.py

sync-contracts:
	cp contracts/db/schema.sql backend/schema.sql
	mkdir -p backend/migrations && cp contracts/db/migrations/*.sql backend/migrations/
	python scripts/gen_enums.py contracts/events/common.schema.json backend/app/contracts/enums.py frontend/src/shared/contracts/enums.ts
	datamodel-codegen --input contracts/events/agent --input-file-type jsonschema --output backend/app/agent/schemas.py --output-model-type pydantic_v2.BaseModel
	datamodel-codegen --input contracts/events/compliance --input-file-type jsonschema --output backend/app/compliance/schemas.py --output-model-type pydantic_v2.BaseModel
	datamodel-codegen --input contracts/events/rules --input-file-type jsonschema --output backend/app/rules/schemas.py --output-model-type pydantic_v2.BaseModel
	datamodel-codegen --input contracts/events/ingest --input-file-type jsonschema --output backend/app/ingest/schemas.py --output-model-type pydantic_v2.BaseModel
	cd frontend && npx openapi-typescript ../contracts/api/openapi.yaml -o src/shared/api/types.ts

dev test lint scenario bench i18n-check:
	@echo "цель $@ реализуется в E1/E11 — см. AGENTS.md раздел 4"

cassettes-record stt-bench demo-offline:
	@echo "цель $@ реализуется в E16/E17 (T-181, T-194, T-197, T-198) — см. AGENTS.md раздел 4"

import-transcripts:
	@echo "цель $@ реализуется в E18 (T-208) — POST /api/ingest/transcripts/import"
