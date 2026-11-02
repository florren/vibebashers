-- T-051: единый реестр credential configuration и snapshot на AgentRun.
-- Operational ledger/UTC quotas сюда не входят (T-050, отдельная миграция).
ALTER TABLE llm_api_keys DROP CONSTRAINT IF EXISTS llm_api_keys_provider_check;
ALTER TABLE llm_api_keys ADD CONSTRAINT llm_api_keys_provider_check CHECK(provider IN ('gigachat','openai_compatible','mock'));
ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS llm_profiles_snapshot jsonb;
ALTER TABLE llm_api_keys ADD COLUMN IF NOT EXISTS credential_uid uuid NOT NULL DEFAULT gen_random_uuid();
ALTER TABLE llm_api_keys ADD COLUMN IF NOT EXISTS endpoint_url text;
ALTER TABLE llm_api_keys ADD COLUMN IF NOT EXISTS scope text;
ALTER TABLE llm_api_keys ADD COLUMN IF NOT EXISTS key_hint text;
ALTER TABLE llm_api_keys ADD COLUMN IF NOT EXISTS rpd_limit integer;
ALTER TABLE llm_api_keys ADD COLUMN IF NOT EXISTS balance_usd numeric;
ALTER TABLE llm_api_keys ADD COLUMN IF NOT EXISTS created_at timestamptz NOT NULL DEFAULT now();
ALTER TABLE llm_api_keys ADD COLUMN IF NOT EXISTS deleted_at timestamptz;
ALTER TABLE llm_profiles ADD COLUMN IF NOT EXISTS api_key_id integer;
DO $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conname='llm_profiles_api_key_fk') THEN
  ALTER TABLE llm_profiles ADD CONSTRAINT llm_profiles_api_key_fk FOREIGN KEY(api_key_id) REFERENCES llm_api_keys(id) ON DELETE RESTRICT;
 END IF;
END $$;
COMMENT ON COLUMN agent_runs.llm_profiles_snapshot IS 'T-051: versioned secret-free role configuration before first LLM; NULL is legacy, not invented history';
COMMENT ON COLUMN llm_api_keys.credential_uid IS 'Private logical identity, never projected by API; no operational counters in model snapshots';
COMMENT ON COLUMN llm_profiles.api_key_id IS 'Explicit credential binding; invalid/revoked/mismatched key never falls back to env';

-- Fail-closed rollback: прежнее приложение не может завести второй writable store.
-- Существующая encrypted legacy row читается конвертером и удаляется только при commit.
CREATE OR REPLACE FUNCTION reject_legacy_llm_key_writes() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.key='llm_keys' THEN
  RAISE EXCEPTION 'Legacy LLM key writes are disabled; use canonical credential registry' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS settings_legacy_llm_key_writes ON settings;
CREATE TRIGGER settings_legacy_llm_key_writes BEFORE INSERT OR UPDATE ON settings
 FOR EACH ROW EXECUTE FUNCTION reject_legacy_llm_key_writes();
