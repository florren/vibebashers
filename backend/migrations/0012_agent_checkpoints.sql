-- Upstream DDL: langgraph-checkpoint-postgres 3.2.0 (MIT).
-- https://github.com/langchain-ai/langgraph/tree/main/libs/checkpoint-postgres
-- MIT License
--
-- Copyright (c) 2024 LangChain, Inc.
--
-- Permission is hereby granted, free of charge, to any person obtaining a copy
-- of this software and associated documentation files (the "Software"), to deal
-- in the Software without restriction, including without limitation the rights
-- to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
-- copies of the Software, and to permit persons to whom the Software is
-- furnished to do so, subject to the following conditions:
--
-- The above copyright notice and this permission notice shall be included in all
-- copies or substantial portions of the Software.
--
-- THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
-- IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
-- FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
-- AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
-- LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
-- OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
-- SOFTWARE.

-- T-041: PostgreSQL checkpointer LangGraph, upstream schema 3.2.0.
CREATE SCHEMA IF NOT EXISTS langgraph;
-- Runtime не выполняет DDL; владение данными определяется FK к sim_runs.


CREATE TABLE IF NOT EXISTS langgraph.checkpoint_migrations (
    v INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS langgraph.checkpoints (
    thread_id TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    checkpoint_id TEXT NOT NULL,
    parent_checkpoint_id TEXT,
    type TEXT,
    checkpoint JSONB NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}',
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
);

CREATE TABLE IF NOT EXISTS langgraph.checkpoint_blobs (
    thread_id TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    channel TEXT NOT NULL,
    version TEXT NOT NULL,
    type TEXT NOT NULL,
    blob BYTEA,
    PRIMARY KEY (thread_id, checkpoint_ns, channel, version)
);

CREATE TABLE IF NOT EXISTS langgraph.checkpoint_writes (
    thread_id TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    checkpoint_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    idx INTEGER NOT NULL,
    channel TEXT NOT NULL,
    type TEXT,
    blob BYTEA NOT NULL,
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
);

ALTER TABLE langgraph.checkpoint_blobs ALTER COLUMN blob DROP not null;

SELECT 1;

CREATE INDEX IF NOT EXISTS checkpoints_thread_id_idx ON langgraph.checkpoints(thread_id);

CREATE INDEX IF NOT EXISTS checkpoint_blobs_thread_id_idx ON langgraph.checkpoint_blobs(thread_id);

CREATE INDEX IF NOT EXISTS checkpoint_writes_thread_id_idx ON langgraph.checkpoint_writes(thread_id);

ALTER TABLE langgraph.checkpoint_writes ADD COLUMN IF NOT EXISTS task_path TEXT NOT NULL DEFAULT '';

INSERT INTO langgraph.checkpoint_migrations(v) SELECT generate_series(0,9) ON CONFLICT DO NOTHING;

ALTER TABLE langgraph.checkpoints ADD COLUMN IF NOT EXISTS run_id bigint GENERATED ALWAYS AS (split_part(thread_id, ':', 1)::bigint) STORED;
DO $$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='checkpoints_run_fk') THEN
  ALTER TABLE langgraph.checkpoints ADD CONSTRAINT checkpoints_run_fk FOREIGN KEY (run_id) REFERENCES sim_runs(id) ON DELETE CASCADE;
 END IF;
END $$;
CREATE INDEX IF NOT EXISTS checkpoints_run_idx ON langgraph.checkpoints(run_id);


ALTER TABLE langgraph.checkpoint_blobs ADD COLUMN IF NOT EXISTS run_id bigint GENERATED ALWAYS AS (split_part(thread_id, ':', 1)::bigint) STORED;
DO $$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='checkpoint_blobs_run_fk') THEN
  ALTER TABLE langgraph.checkpoint_blobs ADD CONSTRAINT checkpoint_blobs_run_fk FOREIGN KEY (run_id) REFERENCES sim_runs(id) ON DELETE CASCADE;
 END IF;
END $$;
CREATE INDEX IF NOT EXISTS checkpoint_blobs_run_idx ON langgraph.checkpoint_blobs(run_id);


ALTER TABLE langgraph.checkpoint_writes ADD COLUMN IF NOT EXISTS run_id bigint GENERATED ALWAYS AS (split_part(thread_id, ':', 1)::bigint) STORED;
DO $$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='checkpoint_writes_run_fk') THEN
  ALTER TABLE langgraph.checkpoint_writes ADD CONSTRAINT checkpoint_writes_run_fk FOREIGN KEY (run_id) REFERENCES sim_runs(id) ON DELETE CASCADE;
 END IF;
END $$;
CREATE INDEX IF NOT EXISTS checkpoint_writes_run_idx ON langgraph.checkpoint_writes(run_id);


-- Исходный outcome не переопределяется: статус прерывания хранится отдельно.
ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS interrupted_at timestamptz;
ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS status text GENERATED ALWAYS AS
 (CASE WHEN outcome IS NULL AND interrupted_at IS NOT NULL THEN 'interrupted'
       ELSE coalesce(outcome,'running') END) STORED;
