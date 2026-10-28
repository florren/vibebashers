-- T-246: natural and composite CSI audit keys; idempotent.
CREATE OR REPLACE FUNCTION log_db_activity() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  v_pk text;
  v_summary jsonb;
  v_row jsonb;
BEGIN
  v_row := CASE WHEN TG_OP = 'DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
  v_pk := coalesce(v_row->>'id', v_row->>'code', v_row->>'signal_id');
  IF v_pk IS NULL AND TG_TABLE_NAME = 'csi_visits_agg' THEN
    v_pk := jsonb_build_array(v_row->>'branch_id', v_row->>'day', v_row->>'wait_bucket', v_row->>'redirects_bucket')::text;
  END IF;
  IF v_pk IS NULL THEN
    RAISE EXCEPTION USING MESSAGE = 'Unsupported audit primary key on ' || TG_TABLE_NAME;
  END IF;
  IF TG_OP = 'DELETE' THEN
    v_summary := jsonb_build_object('deleted', true);
  ELSE
    v_summary := CASE WHEN TG_OP = 'UPDATE'
      THEN (SELECT jsonb_object_agg(key, value) FROM jsonb_each(to_jsonb(NEW))
            WHERE to_jsonb(OLD) -> key IS DISTINCT FROM value)
      ELSE jsonb_build_object('status', to_jsonb(NEW) ->> 'status') END;
  END IF;
  INSERT INTO db_activity_log(table_name, op, pk, summary) VALUES (TG_TABLE_NAME, TG_OP, v_pk, v_summary);
  PERFORM pg_notify('db_activity', json_build_object('table', TG_TABLE_NAME, 'op', TG_OP, 'pk', v_pk)::text);
  RETURN COALESCE(NEW, OLD);
END $$;
