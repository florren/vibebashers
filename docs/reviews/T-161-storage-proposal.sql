-- T-161 REVIEW PROPOSAL: только явная scratch-проверка, НЕ runtimeDDL/миграция0017.
-- Будущий parent0016 проверяется при выпуске реальной forward-only миграции.
DO $$ BEGIN
  IF EXISTS(SELECT 1 FROM client_states WHERE is_current GROUP BY run_id,client_id HAVING count(*)>1) THEN
    RAISE EXCEPTION 'legacy duplicate current client states: explicit operator reconciliation required' USING ERRCODE='23514';
  END IF;
END $$;
CREATE UNIQUE INDEX IF NOT EXISTS behavior_client_states_current_key ON client_states(run_id,client_id) WHERE is_current;

CREATE OR REPLACE FUNCTION valid_behavior_care_snapshot(doc jsonb) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE component text;
BEGIN
  IF jsonb_typeof(doc) IS DISTINCT FROM 'object'
     OR NOT doc ?& ARRAY['version','components','first_reply_at','tone_violated','sla_breached']
     OR (SELECT count(*) FROM jsonb_object_keys(doc))<>5
     OR doc->'version' IS DISTINCT FROM '1'::jsonb
     OR jsonb_typeof(doc->'components') IS DISTINCT FROM 'object'
     OR NOT (doc->'components') ?& ARRAY['proactive','speed','sla','gift_fit','tone','explanation']
     OR (SELECT count(*) FROM jsonb_object_keys(doc->'components'))<>6
     OR jsonb_typeof(doc->'tone_violated') IS DISTINCT FROM 'boolean'
     OR jsonb_typeof(doc->'sla_breached') IS DISTINCT FROM 'boolean'
     OR jsonb_typeof(doc->'first_reply_at') NOT IN ('string','null') THEN
    RETURN false;
  END IF;
  FOREACH component IN ARRAY ARRAY['proactive','speed','sla','gift_fit','tone','explanation'] LOOP
    IF jsonb_typeof(doc->'components'->component) IS DISTINCT FROM 'number' THEN RETURN false; END IF;
    IF (doc->'components'->>component)::numeric NOT BETWEEN 0 AND 1 THEN RETURN false; END IF;
  END LOOP;
  IF (doc->>'tone_violated')::boolean AND (doc->'components'->>'tone')::numeric<>0 THEN RETURN false; END IF;
  IF (doc->>'sla_breached')::boolean AND (doc->'components'->>'sla')::numeric<>0 THEN RETURN false; END IF;
  IF jsonb_typeof(doc->'first_reply_at')='string' THEN
    IF doc->>'first_reply_at' !~ '(Z|[+-][0-9]{2}:[0-9]{2})$' THEN RETURN false; END IF;
    PERFORM (doc->>'first_reply_at')::timestamptz;
  END IF;
  RETURN true;
END $$;

CREATE OR REPLACE FUNCTION behavior_valid_failed_operation(op_id bigint, expected_run bigint) RETURNS boolean
LANGUAGE sql STABLE AS $$
  SELECT EXISTS(
    SELECT 1 FROM operations o JOIN clients c ON c.id=o.client_id
    LEFT JOIN faults f ON f.id=o.fault_id
    WHERE o.id=op_id AND o.run_id=expected_run AND o.status='failed' AND o.error_code IS NOT NULL
      AND (o.fault_id IS NULL OR (f.run_id=o.run_id AND f.error_code=o.error_code
        AND f.system_code=ANY(o.system_path) AND o.started_sim>=f.started_sim
        AND (f.resolved_sim IS NULL OR o.started_sim<f.resolved_sim)
        AND (cardinality(f.region_codes)=0 OR c.region_code=ANY(f.region_codes))))
  );
$$;

CREATE TABLE IF NOT EXISTS behavior_evidence (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id bigint NOT NULL REFERENCES sim_runs(id) ON DELETE CASCADE,
  client_id bigint NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  source_kind text NOT NULL CHECK(source_kind IN ('operation','notification','twin_reaction','sla','resolution','agent_state')),
  source_id bigint NOT NULL CHECK(source_id>0),
  observed_sim timestamptz NOT NULL,
  consumed_sim timestamptz,
  UNIQUE(run_id,client_id,source_kind,source_id)
);
CREATE INDEX IF NOT EXISTS behavior_evidence_due_idx ON behavior_evidence(run_id,observed_sim,id) WHERE consumed_sim IS NULL;
CREATE TABLE IF NOT EXISTS behavior_runtime (
  run_id bigint NOT NULL REFERENCES sim_runs(id) ON DELETE CASCADE,
  client_id bigint NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  episode_no integer NOT NULL CHECK(episode_no>0),
  state_id bigint NOT NULL REFERENCES client_states(id),
  opened_sim timestamptz NOT NULL,
  closed_sim timestamptz,
  psychotype_code text NOT NULL,
  segment_code text NOT NULL,
  first_response_min integer NOT NULL CHECK(first_response_min>0),
  policy_source_sha256 text NOT NULL CHECK(policy_source_sha256 ~ '^[0-9a-f]{64}$'),
  policy_hash text NOT NULL CHECK(policy_hash ~ '^[0-9a-f]{64}$'),
  policy_snapshot jsonb NOT NULL,
  params_snapshot jsonb NOT NULL,
  care_snapshot jsonb NOT NULL CHECK(octet_length(care_snapshot::text)<=4096 AND valid_behavior_care_snapshot(care_snapshot)),
  first_complaint_sim timestamptz,
  patience_due_sim timestamptz NOT NULL,
  repeat_count integer NOT NULL DEFAULT 0 CHECK(repeat_count>=0),
  sla_breached boolean NOT NULL DEFAULT false,
  silent_decline boolean NOT NULL DEFAULT false,
  next_hazard_sim timestamptz NOT NULL,
  PRIMARY KEY(run_id,client_id)
);
CREATE TABLE IF NOT EXISTS behavior_causes (
  run_id bigint NOT NULL,
  client_id bigint NOT NULL,
  episode_no integer NOT NULL CHECK(episode_no>0),
  operation_id bigint NOT NULL REFERENCES operations(id),
  fault_id bigint REFERENCES faults(id),
  PRIMARY KEY(run_id,client_id,operation_id),
  FOREIGN KEY(run_id,client_id) REFERENCES behavior_runtime(run_id,client_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS behavior_work (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id bigint NOT NULL,
  client_id bigint NOT NULL,
  episode_no integer NOT NULL CHECK(episode_no>0),
  status text NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','consumed','cancelled')),
  kind text NOT NULL CHECK(kind IN ('complaint','repeat','patience')),
  source_id bigint NOT NULL CHECK(source_id>0),
  due_sim timestamptz NOT NULL,
  consumed_sim timestamptz,
  UNIQUE(run_id,client_id,episode_no,kind,source_id),
  FOREIGN KEY(run_id,client_id) REFERENCES behavior_runtime(run_id,client_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS behavior_work_due_idx ON behavior_work(run_id,due_sim,id) WHERE status='pending';
CREATE TABLE IF NOT EXISTS behavior_receipts (
  run_id bigint NOT NULL REFERENCES sim_runs(id) ON DELETE CASCADE,
  client_id bigint NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  source_kind text NOT NULL,
  source_id bigint NOT NULL CHECK(source_id>0),
  action text NOT NULL,
  consumed_sim timestamptz NOT NULL,
  PRIMARY KEY(run_id,client_id,source_kind,source_id,action)
);
CREATE TABLE IF NOT EXISTS behavior_tick_receipts (
  run_id bigint NOT NULL REFERENCES sim_runs(id) ON DELETE CASCADE,
  client_id bigint NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  logical_tick_sim timestamptz NOT NULL,
  PRIMARY KEY(run_id,client_id,logical_tick_sim)
);

-- Запрос агента хранится отдельно от результата owner; никаких inferred closure.
CREATE TABLE IF NOT EXISTS behavior_agent_intents (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id bigint NOT NULL REFERENCES sim_runs(id) ON DELETE CASCADE,
  agent_run_id bigint NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
  client_id bigint NOT NULL REFERENCES clients(id),
  signal_id bigint NOT NULL REFERENCES signals(id),
  incident_id bigint REFERENCES incidents(id),
  requested_state text NOT NULL CHECK(requested_state IN ('calm','affected','complaining','waiting','asks_again','escalates','satisfied','churn_intent','retained','churned')),
  trigger text NOT NULL CHECK(length(trigger) BETWEEN 1 AND 128),
  observed_sim timestamptz NOT NULL,
  UNIQUE NULLS NOT DISTINCT(run_id,agent_run_id,client_id,signal_id,incident_id,requested_state,trigger)
);

-- Только новые или действительно пустые run; legacy timers не восстанавливаем догадкой.
CREATE TABLE IF NOT EXISTS behavior_runs (
  run_id bigint PRIMARY KEY REFERENCES sim_runs(id) ON DELETE CASCADE,
  policy_hash text NOT NULL CHECK(length(policy_hash)=64),
  activated_sim timestamptz NOT NULL
);
CREATE TABLE IF NOT EXISTS behavior_pending_signals (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id bigint NOT NULL REFERENCES sim_runs(id) ON DELETE CASCADE,
  client_id bigint NOT NULL REFERENCES clients(id),
  due_sim timestamptz NOT NULL,
  client_snapshot jsonb NOT NULL CHECK(jsonb_typeof(client_snapshot)='object' AND octet_length(client_snapshot::text)<=16384),
  signal_type text NOT NULL,
  product_code text NOT NULL REFERENCES products(code),
  source_operation_id bigint REFERENCES operations(id) ON DELETE CASCADE,
  source_fault_id bigint REFERENCES faults(id) ON DELETE CASCADE,
  error_code text REFERENCES error_codes(code),
  system_code text REFERENCES systems(code),
  correlation_id uuid NOT NULL,
  consumed_sim timestamptz
);
CREATE INDEX IF NOT EXISTS behavior_pending_due_idx ON behavior_pending_signals(run_id,due_sim,id) WHERE consumed_sim IS NULL;
