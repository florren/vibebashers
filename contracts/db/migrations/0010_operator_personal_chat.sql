-- T-268/T-269: обработка дополнений операторов и изолированный анонимный чат.
ALTER TABLE agent_runs DROP CONSTRAINT IF EXISTS agent_runs_kind_check;
ALTER TABLE agent_runs ADD CONSTRAINT agent_runs_kind_check CHECK (kind IN
 ('agent','client_twin','team_emulator','bench','compare','compliance_detector','speaker_attribution','operator_review'));
CREATE TABLE IF NOT EXISTS hitl_feedback_processing (
 feedback_id bigint PRIMARY KEY REFERENCES hitl_feedback(id) ON DELETE CASCADE,
 status text NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','applied','failed')),
 attempts integer NOT NULL DEFAULT 0,
 retry_at timestamptz NOT NULL DEFAULT now(),
 agent_run_id bigint REFERENCES agent_runs(id),
 review jsonb,
 applied_at timestamptz,
 error text
);
CREATE INDEX IF NOT EXISTS hitl_feedback_pending_idx ON hitl_feedback_processing(status,retry_at);
INSERT INTO hitl_feedback_processing(feedback_id) SELECT id FROM hitl_feedback ON CONFLICT DO NOTHING;
CREATE OR REPLACE FUNCTION queue_operator_feedback() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 INSERT INTO hitl_feedback_processing(feedback_id) VALUES (NEW.id) ON CONFLICT DO NOTHING;
 PERFORM pg_notify('operator_feedback', NEW.id::text);
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS hitl_feedback_queue ON hitl_feedback;
CREATE TRIGGER hitl_feedback_queue AFTER INSERT ON hitl_feedback FOR EACH ROW EXECUTE FUNCTION queue_operator_feedback();
CREATE TABLE IF NOT EXISTS personal_chat_sessions (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 token_hash text NOT NULL UNIQUE,
 run_id bigint REFERENCES sim_runs(id) ON DELETE CASCADE,
 created_at timestamptz NOT NULL DEFAULT now(),
 last_message_at timestamptz
);
CREATE TABLE IF NOT EXISTS personal_chat_messages (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 session_id bigint NOT NULL REFERENCES personal_chat_sessions(id) ON DELETE CASCADE,
 request_id uuid NOT NULL,
 request_hash text NOT NULL CHECK(length(request_hash)=64),
 signal_id bigint NOT NULL UNIQUE REFERENCES signals(id) ON DELETE CASCADE,
 created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(session_id,request_id)
);
CREATE INDEX IF NOT EXISTS personal_chat_history_idx ON personal_chat_messages(session_id,id);

CREATE INDEX IF NOT EXISTS personal_chat_rate_idx ON personal_chat_messages(created_at);
CREATE INDEX IF NOT EXISTS personal_session_rate_idx ON personal_chat_sessions(created_at);
