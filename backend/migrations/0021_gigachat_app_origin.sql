-- API balance is not historical consumption. Preserve a one-time application
-- accounting origin and its unknown pre-registration history outside bank restore.
CREATE TABLE IF NOT EXISTS llm_runtime.gigachat_app_origins (
    credential_uid uuid PRIMARY KEY REFERENCES llm_runtime.credentials(uid),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    source text NOT NULL DEFAULT 'gigachat_api_balance_app_origin'
        CHECK (source = 'gigachat_api_balance_app_origin'),
    historical_usage_known boolean NOT NULL DEFAULT false CHECK (NOT historical_usage_known),
    observation jsonb NOT NULL CHECK (jsonb_typeof(observation) = 'object')
);
COMMENT ON TABLE llm_runtime.gigachat_app_origins IS
    'One-time application usage origin; provider balance is a remaining package, never historic usage. Preserve on rollback/restore.';
