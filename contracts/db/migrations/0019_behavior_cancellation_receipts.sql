-- T-039 B: только provenance отмены; legacy NULL не восстанавливается догадкой.
ALTER TABLE public.behavior_receipts ADD COLUMN IF NOT EXISTS details jsonb;

CREATE OR REPLACE FUNCTION public.valid_behavior_cancellation_details(
  p_source_kind text, p_action text, p_consumed_sim timestamptz, p_doc jsonb
) RETURNS boolean LANGUAGE plpgsql STABLE AS $$
DECLARE
  key text;
  keys text[] := ARRAY['version','episode_no','work_kind','due_sim','cancellation_sim',
    'cancellation_observed_sim','first_complaint_sim_at_cancellation','complaint_observation_complete',
    'evidence_id','evidence_kind','evidence_source_id','canonical_signal_id','resolution_sim'];
  stamp_pattern text := '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?(Z|[+-][0-9]{2}:[0-9]{2})$';
BEGIN
  IF p_doc IS NULL THEN RETURN true; END IF;
  IF jsonb_typeof(p_doc) IS DISTINCT FROM 'object' OR octet_length(p_doc::text)>2048 THEN RETURN false; END IF;
  IF NOT (p_doc ?& keys) OR EXISTS(SELECT 1 FROM jsonb_object_keys(p_doc) k WHERE NOT k=ANY(keys)) THEN RETURN false; END IF;
  IF p_source_kind IS DISTINCT FROM 'work' OR p_action IS NULL OR p_action NOT IN ('cancelled_by_resolution','already_complained') THEN RETURN false; END IF;
  IF jsonb_typeof(p_doc->'version') IS DISTINCT FROM 'number' OR p_doc->>'version'<>'1' THEN RETURN false; END IF;
  FOREACH key IN ARRAY ARRAY['episode_no','evidence_id','evidence_source_id'] LOOP
    IF jsonb_typeof(p_doc->key) IS DISTINCT FROM 'number' THEN RETURN false; END IF;
    IF (p_doc->>key) !~ '^[1-9][0-9]*$' THEN RETURN false; END IF;
    IF (p_doc->>key)::numeric>9223372036854775807 THEN RETURN false; END IF;
  END LOOP;
  IF (p_doc->>'episode_no')::numeric>2147483647 THEN RETURN false; END IF;
  IF jsonb_typeof(p_doc->'canonical_signal_id') IS DISTINCT FROM 'null' THEN
    IF jsonb_typeof(p_doc->'canonical_signal_id') IS DISTINCT FROM 'number' THEN RETURN false; END IF;
    IF p_doc->>'canonical_signal_id' !~ '^[1-9][0-9]*$' THEN RETURN false; END IF;
    IF (p_doc->>'canonical_signal_id')::numeric>9223372036854775807 THEN RETURN false; END IF;
  END IF;
  IF p_doc->>'work_kind' NOT IN ('complaint','repeat','patience') OR
    jsonb_typeof(p_doc->'work_kind') IS DISTINCT FROM 'string' OR
    p_doc->>'evidence_kind' NOT IN ('resolution','agent_state') OR
    jsonb_typeof(p_doc->'evidence_kind') IS DISTINCT FROM 'string' OR
    jsonb_typeof(p_doc->'complaint_observation_complete') IS DISTINCT FROM 'boolean' THEN RETURN false; END IF;
  FOREACH key IN ARRAY ARRAY['due_sim','cancellation_sim','cancellation_observed_sim',
    'first_complaint_sim_at_cancellation','resolution_sim'] LOOP
    IF key IN ('first_complaint_sim_at_cancellation','resolution_sim') AND jsonb_typeof(p_doc->key)='null' THEN CONTINUE; END IF;
    IF jsonb_typeof(p_doc->key) IS DISTINCT FROM 'string' OR p_doc->>key !~ stamp_pattern THEN RETURN false; END IF;
    IF NOT pg_catalog.pg_input_is_valid(p_doc->>key,'timestamp with time zone') THEN RETURN false; END IF;
  END LOOP;
  IF (p_doc->>'cancellation_sim')::timestamptz IS DISTINCT FROM p_consumed_sim OR
    (p_doc->>'cancellation_observed_sim')::timestamptz<(p_doc->>'cancellation_sim')::timestamptz THEN RETURN false; END IF;
  FOREACH key IN ARRAY ARRAY['first_complaint_sim_at_cancellation','resolution_sim'] LOOP
    IF jsonb_typeof(p_doc->key)<>'null' AND (p_doc->>key)::timestamptz>(p_doc->>'cancellation_sim')::timestamptz THEN RETURN false; END IF;
  END LOOP;
  IF p_action='cancelled_by_resolution' THEN
    RETURN p_doc->>'evidence_kind'='resolution';
  END IF;
  RETURN p_doc->>'evidence_kind'='agent_state' AND p_doc->>'work_kind'='complaint'
    AND jsonb_typeof(p_doc->'canonical_signal_id')='number'
    AND jsonb_typeof(p_doc->'first_complaint_sim_at_cancellation')='string'
    AND jsonb_typeof(p_doc->'resolution_sim')='null';
END $$;

DO $$ BEGIN
  IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conrelid='public.behavior_receipts'::regclass AND conname='behavior_cancellation_details_valid') THEN
    ALTER TABLE public.behavior_receipts ADD CONSTRAINT behavior_cancellation_details_valid
      CHECK(public.valid_behavior_cancellation_details(source_kind,action,consumed_sim,details));
  END IF;
END $$;
COMMENT ON COLUMN public.behavior_receipts.details IS
  'T039 B v1: native provenance отмены; NULL остаётся неизвестным, без legacy backfill и attribution к Sent';
