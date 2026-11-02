-- T-108: аддитивный снимок run_id; старые записи не переписываются и не переатрибутируются.
ALTER TABLE db_activity_log ADD COLUMN IF NOT EXISTS run_id bigint;
CREATE INDEX IF NOT EXISTS db_activity_log_run_id_idx ON db_activity_log (run_id, id DESC);
CREATE OR REPLACE FUNCTION log_db_activity() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  v_pk text;
  v_row jsonb;
  v_run bigint;
  v_summary jsonb;
BEGIN
  v_row := CASE WHEN TG_OP = 'DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
  v_pk := coalesce(v_row->>'id', v_row->>'code', v_row->>'signal_id', v_row->>'incident_id');
  IF TG_TABLE_NAME = 'incident_signals' THEN
    v_pk := jsonb_build_array(v_row->>'incident_id', v_row->>'signal_id')::text;
  ELSIF TG_TABLE_NAME = 'csi_visits_agg' THEN
    v_pk := jsonb_build_array(v_row->>'branch_id', v_row->>'day', v_row->>'wait_bucket', v_row->>'redirects_bucket')::text;
  END IF;
  IF v_pk IS NULL THEN
    RAISE EXCEPTION USING MESSAGE = 'Unsupported audit primary key on ' || TG_TABLE_NAME;
  END IF;
  IF TG_TABLE_NAME = 'agent_steps' THEN
    SELECT sim_run_id INTO v_run FROM agent_runs WHERE id = (v_row->>'run_id')::bigint;
  ELSIF TG_TABLE_NAME = 'agent_runs' THEN
    v_run := (v_row->>'sim_run_id')::bigint;
  ELSIF v_row ? 'run_id' THEN
    v_run := (v_row->>'run_id')::bigint;
  ELSIF TG_TABLE_NAME IN ('incident_signals', 'incident_status_history') THEN
    SELECT run_id INTO v_run FROM incidents WHERE id = (v_row->>'incident_id')::bigint;
  END IF;
  -- Аудит содержит только имена изменённых полей, не контакты/промпты/секреты.
  v_summary := jsonb_build_object('changed_fields', CASE WHEN TG_OP = 'UPDATE'
    THEN (SELECT coalesce(jsonb_agg(key ORDER BY key), '[]'::jsonb) FROM jsonb_each(v_row)
          WHERE to_jsonb(OLD)->key IS DISTINCT FROM value)
    ELSE '[]'::jsonb END);
  INSERT INTO db_activity_log(run_id, table_name, op, pk, summary)
    VALUES (v_run, TG_TABLE_NAME, TG_OP, v_pk, v_summary);
  PERFORM pg_notify('db_activity', json_build_object('table', TG_TABLE_NAME, 'op', TG_OP, 'pk', v_pk, 'run_id', v_run)::text);
  RETURN COALESCE(NEW, OLD);
END $$;

DROP TRIGGER IF EXISTS incident_signals_activity ON incident_signals;
CREATE TRIGGER incident_signals_activity AFTER INSERT OR UPDATE OR DELETE ON incident_signals FOR EACH ROW EXECUTE FUNCTION log_db_activity();
DROP TRIGGER IF EXISTS incident_status_history_activity ON incident_status_history;
CREATE TRIGGER incident_status_history_activity AFTER INSERT OR UPDATE OR DELETE ON incident_status_history FOR EACH ROW EXECUTE FUNCTION log_db_activity();
DROP TRIGGER IF EXISTS agent_steps_activity ON agent_steps;
CREATE TRIGGER agent_steps_activity AFTER INSERT OR UPDATE OR DELETE ON agent_steps FOR EACH ROW EXECUTE FUNCTION log_db_activity();
DROP TRIGGER IF EXISTS client_states_activity ON client_states;
CREATE TRIGGER client_states_activity AFTER INSERT OR UPDATE OR DELETE ON client_states FOR EACH ROW EXECUTE FUNCTION log_db_activity();
DROP TRIGGER IF EXISTS churn_events_activity ON churn_events;
CREATE TRIGGER churn_events_activity AFTER INSERT OR UPDATE OR DELETE ON churn_events FOR EACH ROW EXECUTE FUNCTION log_db_activity();
DROP TRIGGER IF EXISTS incident_economics_activity ON incident_economics;
CREATE TRIGGER incident_economics_activity AFTER INSERT OR UPDATE OR DELETE ON incident_economics FOR EACH ROW EXECUTE FUNCTION log_db_activity();
DROP TRIGGER IF EXISTS faults_activity ON faults;
CREATE TRIGGER faults_activity AFTER INSERT OR UPDATE OR DELETE ON faults FOR EACH ROW EXECUTE FUNCTION log_db_activity();
