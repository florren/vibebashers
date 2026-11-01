-- T-267: неизменяемая информация оператора, доступная после продолжения процесса.
CREATE TABLE IF NOT EXISTS hitl_feedback (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  human_decision_id bigint NOT NULL REFERENCES human_decisions(id) ON DELETE CASCADE,
  idempotency_key text NOT NULL CHECK (length(idempotency_key) BETWEEN 1 AND 120),
  comment text NOT NULL CHECK (length(btrim(comment)) BETWEEN 1 AND 4000),
  recorded_by text NOT NULL CHECK (length(btrim(recorded_by)) BETWEEN 1 AND 120),
  recorded_sim timestamptz NOT NULL,
  recorded_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (human_decision_id,idempotency_key)
);
CREATE INDEX IF NOT EXISTS hitl_feedback_history_idx ON hitl_feedback (human_decision_id,id DESC);
CREATE OR REPLACE FUNCTION reject_hitl_feedback_update() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'hitl_feedback is append-only; add a new record';
END $$;
DROP TRIGGER IF EXISTS hitl_feedback_immutable ON hitl_feedback;
CREATE TRIGGER hitl_feedback_immutable BEFORE UPDATE ON hitl_feedback
FOR EACH ROW EXECUTE FUNCTION reject_hitl_feedback_update();
DROP TRIGGER IF EXISTS hitl_feedback_activity ON hitl_feedback;
CREATE TRIGGER hitl_feedback_activity AFTER INSERT ON hitl_feedback
FOR EACH ROW EXECUTE FUNCTION log_db_activity();
