-- T-265: неизменяемые версии доказательств; сумма и основания берутся из согласованной политики.
CREATE TABLE IF NOT EXISTS financial_evidence (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id bigint NOT NULL REFERENCES sim_runs(id) ON DELETE CASCADE,
  incident_id bigint NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
  alert_id bigint NOT NULL REFERENCES compliance_alerts(id),
  scope text NOT NULL CHECK (scope IN ('demo','observed')),
  deal_ref text NOT NULL CHECK (length(deal_ref) BETWEEN 1 AND 120),
  idempotency_key text NOT NULL CHECK (length(idempotency_key) BETWEEN 1 AND 120),
  payload_sha256 text NOT NULL CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
  intervention_sim timestamptz NOT NULL,
  deal_closed_sim timestamptz NOT NULL,
  outcome text NOT NULL CHECK (outcome IN ('prevented','completed','unknown')),
  evidence_ref text NOT NULL CHECK (length(evidence_ref) BETWEEN 1 AND 500),
  recorded_by text NOT NULL CHECK (length(recorded_by) BETWEEN 1 AND 120),
  policy jsonb NOT NULL,
  policy_sha256 text NOT NULL CHECK (policy_sha256 ~ '^[0-9a-f]{64}$'),
  recorded_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (run_id, scope, idempotency_key)
);
CREATE INDEX IF NOT EXISTS financial_evidence_deal_idx ON financial_evidence (run_id, scope, deal_ref, id DESC);
CREATE INDEX IF NOT EXISTS financial_evidence_incident_idx ON financial_evidence (incident_id, scope, id DESC);
CREATE OR REPLACE FUNCTION reject_financial_evidence_update() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'financial_evidence is append-only; add a new version';
END $$;
DROP TRIGGER IF EXISTS financial_evidence_immutable ON financial_evidence;
CREATE TRIGGER financial_evidence_immutable BEFORE UPDATE ON financial_evidence
FOR EACH ROW EXECUTE FUNCTION reject_financial_evidence_update();
DROP TRIGGER IF EXISTS financial_evidence_activity ON financial_evidence;
CREATE TRIGGER financial_evidence_activity AFTER INSERT ON financial_evidence
FOR EACH ROW EXECUTE FUNCTION log_db_activity();
