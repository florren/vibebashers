-- =============================================================================
-- CX Pulse Control — миграция 0004 «След и поиск» (контракт v1.5, ТЗ 27–28, ADR-0008)
-- Идемпотентна: на чистой БД после 0001 (schema.sql v1.5) — no-op; на БД v1.4 — применяет изменения.
-- Исполняется alembic-ревизией 0004_trace_search (op.execute этого файла).
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- -----------------------------------------------------------------------------
-- A. Генерируемые public_id (ТЗ 28.2, 20.7 № 62)
-- -----------------------------------------------------------------------------
ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS public_id text GENERATED ALWAYS AS ('AR-' || lpad(id::text, 6, '0')) STORED;
ALTER TABLE sim_runs ADD COLUMN IF NOT EXISTS public_id text GENERATED ALWAYS AS ('SR-' || lpad(id::text, 4, '0')) STORED;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS public_id text GENERATED ALWAYS AS ('TSK-' || lpad(id::text, 6, '0')) STORED;
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS public_id text GENERATED ALWAYS AS ('NTF-' || lpad(id::text, 6, '0')) STORED;
ALTER TABLE ledger_entries ADD COLUMN IF NOT EXISTS public_id text GENERATED ALWAYS AS ('LED-' || lpad(id::text, 6, '0')) STORED;
ALTER TABLE human_decisions ADD COLUMN IF NOT EXISTS public_id text GENERATED ALWAYS AS ('HD-' || lpad(id::text, 6, '0')) STORED;
ALTER TABLE followups ADD COLUMN IF NOT EXISTS public_id text GENERATED ALWAYS AS ('FUP-' || lpad(id::text, 6, '0')) STORED;

CREATE UNIQUE INDEX IF NOT EXISTS agent_runs_public_id_uidx ON agent_runs (public_id);
CREATE UNIQUE INDEX IF NOT EXISTS sim_runs_public_id_uidx ON sim_runs (public_id);
CREATE UNIQUE INDEX IF NOT EXISTS tasks_public_id_uidx ON tasks (public_id);
CREATE UNIQUE INDEX IF NOT EXISTS notifications_public_id_uidx ON notifications (public_id);
CREATE UNIQUE INDEX IF NOT EXISTS ledger_entries_public_id_uidx ON ledger_entries (public_id);
CREATE UNIQUE INDEX IF NOT EXISTS human_decisions_public_id_uidx ON human_decisions (public_id);
CREATE UNIQUE INDEX IF NOT EXISTS followups_public_id_uidx ON followups (public_id);

-- -----------------------------------------------------------------------------
-- B. Полнотекстовый и триграммный поиск (ТЗ 28.2)
-- -----------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS signals_text_fts_idx ON signals USING gin (to_tsvector('russian', text));
CREATE INDEX IF NOT EXISTS incidents_title_fts_idx ON incidents USING gin (to_tsvector('russian', title));
CREATE INDEX IF NOT EXISTS external_posts_text_fts_idx ON external_posts USING gin (to_tsvector('russian', text));

CREATE INDEX IF NOT EXISTS agent_runs_public_id_trgm_idx ON agent_runs USING gin (public_id gin_trgm_ops);
CREATE INDEX IF NOT EXISTS sim_runs_public_id_trgm_idx ON sim_runs USING gin (public_id gin_trgm_ops);
CREATE INDEX IF NOT EXISTS tasks_public_id_trgm_idx ON tasks USING gin (public_id gin_trgm_ops);
CREATE INDEX IF NOT EXISTS notifications_public_id_trgm_idx ON notifications USING gin (public_id gin_trgm_ops);
CREATE INDEX IF NOT EXISTS ledger_entries_public_id_trgm_idx ON ledger_entries USING gin (public_id gin_trgm_ops);
CREATE INDEX IF NOT EXISTS human_decisions_public_id_trgm_idx ON human_decisions USING gin (public_id gin_trgm_ops);
CREATE INDEX IF NOT EXISTS followups_public_id_trgm_idx ON followups USING gin (public_id gin_trgm_ops);
CREATE INDEX IF NOT EXISTS clients_social_handles_trgm_idx ON clients USING gin ((social_handles::text) gin_trgm_ops);

-- -----------------------------------------------------------------------------
-- C. Индексы по FK цепочки следа (ТЗ 28.7)
-- -----------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS incident_signals_incident_idx ON incident_signals (incident_id);
CREATE INDEX IF NOT EXISTS tasks_incident_idx ON tasks (incident_id) WHERE incident_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS external_replies_incident_idx ON external_replies (incident_id) WHERE incident_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS external_replies_agent_run_idx ON external_replies (agent_run_id) WHERE agent_run_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS client_reactions_notification_idx ON client_reactions (notification_id) WHERE notification_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS client_reactions_agent_run_idx ON client_reactions (agent_run_id) WHERE agent_run_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS followups_incident_idx ON followups (incident_id) WHERE incident_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS followups_signal_idx ON followups (signal_id) WHERE signal_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS followups_agent_run_idx ON followups (agent_run_id) WHERE agent_run_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS human_decisions_incident_idx ON human_decisions (incident_id) WHERE incident_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS human_decisions_signal_idx ON human_decisions (signal_id) WHERE signal_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS human_decisions_agent_run_idx ON human_decisions (agent_run_id) WHERE agent_run_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS escalations_incident_idx ON escalations (incident_id) WHERE incident_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS escalations_signal_idx ON escalations (signal_id) WHERE signal_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS escalations_agent_run_idx ON escalations (agent_run_id) WHERE agent_run_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ledger_entries_agent_run_idx ON ledger_entries (agent_run_id) WHERE agent_run_id IS NOT NULL;
