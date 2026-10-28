-- T-239: audit natural keys and expose red-word markers. Idempotent.
CREATE OR REPLACE FUNCTION log_db_activity() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  v_pk text;
  v_summary jsonb;
BEGIN
  IF TG_OP = 'DELETE' THEN
    v_pk := coalesce(to_jsonb(OLD)->>'id', to_jsonb(OLD)->>'code');
    v_summary := jsonb_build_object('deleted', true);
  ELSE
    v_pk := coalesce(to_jsonb(NEW)->>'id', to_jsonb(NEW)->>'code');
    v_summary := CASE WHEN TG_OP = 'UPDATE'
      THEN (SELECT jsonb_object_agg(key, value) FROM jsonb_each(to_jsonb(NEW))
            WHERE to_jsonb(OLD) -> key IS DISTINCT FROM value)
      ELSE jsonb_build_object('status', to_jsonb(NEW) ->> 'status') END;
  END IF;
  INSERT INTO db_activity_log(table_name, op, pk, summary) VALUES (TG_TABLE_NAME, TG_OP, v_pk, v_summary);
  PERFORM pg_notify('db_activity', json_build_object('table', TG_TABLE_NAME, 'op', TG_OP, 'pk', v_pk)::text);
  RETURN COALESCE(NEW, OLD);
END $$;
