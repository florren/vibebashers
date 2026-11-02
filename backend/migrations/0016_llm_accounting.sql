-- T-050: operational accounting survives bank seed/restore; no FK into public.
-- Stable configuration identity: numeric IDs can be reused after bank restore.
ALTER TABLE public.llm_profiles ADD COLUMN IF NOT EXISTS quota_uid uuid NOT NULL DEFAULT gen_random_uuid();
DO $$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='llm_profiles_quota_uid_key') THEN
  ALTER TABLE public.llm_profiles ADD CONSTRAINT llm_profiles_quota_uid_key UNIQUE (quota_uid);
 END IF;
END $$;
COMMENT ON COLUMN public.llm_profiles.quota_uid IS 'Private budget configuration identity; no API/AR/export projection; not usage';
CREATE SCHEMA IF NOT EXISTS llm_runtime;
CREATE TABLE IF NOT EXISTS llm_runtime.identity_settings (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    secret_tag bytea NOT NULL CHECK (octet_length(secret_tag) = 32),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS llm_runtime.credentials (
    uid uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    provider text NOT NULL CHECK (provider IN ('gigachat', 'openai_compatible')),
    verifier bytea UNIQUE NOT NULL CHECK (octet_length(verifier) = 32),
    confirmed_tokens bigint NOT NULL DEFAULT 0 CHECK (confirmed_tokens >= 0),
    legacy_tokens_hint bigint NOT NULL DEFAULT 0 CHECK (legacy_tokens_hint >= 0),
    usage_known boolean NOT NULL DEFAULT false,
    usage_source text NOT NULL DEFAULT 'unknown',
    usage_as_of timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS llm_runtime.credential_aliases (
    config_uid uuid PRIMARY KEY,
    credential_uid uuid NOT NULL REFERENCES llm_runtime.credentials(uid),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS llm_runtime.profile_scopes (
    scope text PRIMARY KEY,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS llm_runtime.daily_usage (
    scope_type text NOT NULL CHECK (scope_type IN ('key', 'profile')),
    scope_id text NOT NULL,
    utc_day date NOT NULL,
    requests_today bigint NOT NULL DEFAULT 0 CHECK (requests_today >= 0),
    requests_known boolean NOT NULL DEFAULT false,
    usage_source text NOT NULL DEFAULT 'unknown',
    usage_as_of timestamptz,
    PRIMARY KEY (scope_type, scope_id, utc_day)
);
CREATE TABLE IF NOT EXISTS llm_runtime.reconciliations (
    id uuid PRIMARY KEY,
    credential_uid uuid NOT NULL REFERENCES llm_runtime.credentials(uid),
    as_of timestamptz NOT NULL,
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    source text NOT NULL CHECK (source = 'operator_declared_app_usage'),
    observation jsonb NOT NULL CHECK (jsonb_typeof(observation) = 'object')
);
CREATE TABLE IF NOT EXISTS llm_runtime.wire_attempts (
    id uuid PRIMARY KEY,
    credential_uid uuid NOT NULL REFERENCES llm_runtime.credentials(uid),
    profile_scope text NOT NULL,
    profile_id integer,
    profile_code text NOT NULL,
    endpoint text NOT NULL,
    model text NOT NULL,
    utc_day date NOT NULL,
    admitted_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    deadline_at timestamptz NOT NULL,
    finished_at timestamptz,
    state text NOT NULL DEFAULT 'reserved' CHECK (state IN ('reserved', 'known', 'unknown', 'reconciled')),
    prompt_tokens bigint CHECK (prompt_tokens >= 0),
    completion_tokens bigint CHECK (completion_tokens >= 0),
    observed_tokens bigint NOT NULL DEFAULT 0 CHECK (observed_tokens >= 0),
    error_kind text,
    reconciliation_id uuid REFERENCES llm_runtime.reconciliations(id),
    CHECK (state <> 'known' OR (prompt_tokens IS NOT NULL AND completion_tokens IS NOT NULL AND finished_at IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS wire_attempts_key_day_idx
    ON llm_runtime.wire_attempts (credential_uid, utc_day, admitted_at);
CREATE INDEX IF NOT EXISTS wire_attempts_profile_day_idx
    ON llm_runtime.wire_attempts (profile_scope, utc_day, admitted_at);

-- Idempotent for a partially installed development checkpoint as well.
ALTER TABLE llm_runtime.wire_attempts ADD COLUMN IF NOT EXISTS profile_id integer;
ALTER TABLE llm_runtime.wire_attempts ADD COLUMN IF NOT EXISTS profile_code text NOT NULL DEFAULT '';
