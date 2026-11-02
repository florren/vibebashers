-- T-248: известные знаменатели только из атомарно зарегистрированной CSI когорты.
-- Legacy csi_visits_agg остаётся без backfill: её run/линия/coverage неизвестны.
CREATE UNIQUE INDEX IF NOT EXISTS signals_csi_run_key ON signals(id,run_id);
CREATE UNIQUE INDEX IF NOT EXISTS csi_responses_branch_key ON csi_responses(signal_id,branch_id);

CREATE TABLE IF NOT EXISTS csi_cohorts (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id bigint NOT NULL REFERENCES sim_runs(id) ON DELETE CASCADE,
  dataset_code text NOT NULL CHECK (dataset_code ~ '^[a-z][a-z0-9_]{2,63}$'),
  dataset_digest text NOT NULL CHECK (dataset_digest ~ '^[0-9a-f]{64}$'),
  directory_digest text NOT NULL CHECK (directory_digest ~ '^[0-9a-f]{64}$'),
  visits_digest text NOT NULL CHECK (visits_digest ~ '^[0-9a-f]{64}$'),
  members_digest text NOT NULL CHECK (members_digest ~ '^[0-9a-f]{64}$'),
  branch_id integer NOT NULL REFERENCES branches(id),
  product_line_code text NOT NULL REFERENCES product_lines(code),
  window_start timestamptz NOT NULL,
  window_end timestamptz NOT NULL,
  is_synthetic boolean NOT NULL,
  member_count integer NOT NULL CHECK (member_count BETWEEN 1 AND 300),
  registered_at timestamptz NOT NULL DEFAULT now(),
  CHECK (isfinite(window_start) AND isfinite(window_end) AND window_start < window_end),
  UNIQUE (run_id,dataset_code,branch_id),
  UNIQUE (id,run_id,branch_id),
  UNIQUE (id,run_id)
);

CREATE TABLE IF NOT EXISTS csi_cohort_visits (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  cohort_id bigint NOT NULL,
  run_id bigint NOT NULL REFERENCES sim_runs(id) ON DELETE CASCADE,
  wait_bucket text NOT NULL CHECK (wait_bucket IN ('0-5','5-15','15-30','30+')),
  redirects_bucket text NOT NULL CHECK (redirects_bucket IN ('0','1','2+')),
  visits integer NOT NULL CHECK (visits >= 0),
  UNIQUE (cohort_id,wait_bucket,redirects_bucket),
  FOREIGN KEY (cohort_id,run_id) REFERENCES csi_cohorts(id,run_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS csi_cohort_members (
  signal_id bigint PRIMARY KEY,
  cohort_id bigint NOT NULL,
  run_id bigint NOT NULL REFERENCES sim_runs(id) ON DELETE CASCADE,
  branch_id integer NOT NULL,
  response_at timestamptz NOT NULL CHECK (isfinite(response_at)),
  wait_bucket text NOT NULL,
  redirects_bucket text NOT NULL,
  FOREIGN KEY (signal_id,run_id) REFERENCES signals(id,run_id) ON DELETE CASCADE,
  FOREIGN KEY (signal_id,branch_id) REFERENCES csi_responses(signal_id,branch_id) ON DELETE CASCADE,
  FOREIGN KEY (cohort_id,run_id,branch_id) REFERENCES csi_cohorts(id,run_id,branch_id) ON DELETE CASCADE,
  FOREIGN KEY (cohort_id,wait_bucket,redirects_bucket)
    REFERENCES csi_cohort_visits(cohort_id,wait_bucket,redirects_bucket) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS csi_cohorts_scope_idx ON csi_cohorts(run_id,product_line_code,window_start,window_end);
CREATE INDEX IF NOT EXISTS csi_cohort_members_cohort_idx ON csi_cohort_members(cohort_id);

-- Один reader snapshot без передачи всех membership rows приложению. JSON
-- содержит лишь integer/ASCII enums/UTC timestamp, не клиентский текст.
-- COLLATE C и ровно6 fractional digits совпадают с Python fingerprint codec.
CREATE OR REPLACE VIEW v_csi_cohort_integrity AS
SELECT c.*,v.visit_cells,v.visits AS sample_visits,m.members AS actual_members,
  (v.fingerprint=c.visits_digest AND m.fingerprint=c.members_digest AND m.members=c.member_count) AS is_complete
FROM csi_cohorts c
CROSS JOIN LATERAL (
  SELECT count(*) AS visit_cells,coalesce(sum(x.visits),0) AS visits,
    encode(sha256(convert_to(replace(coalesce(jsonb_agg(jsonb_build_array(x.wait_bucket,x.redirects_bucket,x.visits)
      ORDER BY x.wait_bucket COLLATE "C",x.redirects_bucket COLLATE "C"),'[]'::jsonb)::text,' ',''),'UTF8')),'hex') AS fingerprint
  FROM csi_cohort_visits x WHERE x.cohort_id=c.id
) v
CROSS JOIN LATERAL (
  SELECT count(*) AS members,
    encode(sha256(convert_to(replace(coalesce(jsonb_agg(jsonb_build_array(x.signal_id,
      to_char(x.response_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US')||'+00:00',x.wait_bucket,x.redirects_bucket)
      ORDER BY x.signal_id),'[]'::jsonb)::text,' ',''),'UTF8')),'hex') AS fingerprint
  FROM csi_cohort_members x WHERE x.cohort_id=c.id
) m;

-- Установка проверяет исходный payload/digest/roster; SQL граница дополнительно
-- запрещает межзапусковую/межфилиальную membership и дату вне [start,end).
CREATE OR REPLACE FUNCTION check_csi_cohort_member_time() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE lo timestamptz; hi timestamptz;
BEGIN
  SELECT window_start,window_end INTO lo,hi FROM csi_cohorts
   WHERE id=NEW.cohort_id AND run_id=NEW.run_id AND branch_id=NEW.branch_id FOR KEY SHARE;
  IF NOT FOUND OR NEW.response_at < lo OR NEW.response_at >= hi THEN
    RAISE EXCEPTION 'CSI response outside cohort window' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS csi_cohort_member_time ON csi_cohort_members;
CREATE TRIGGER csi_cohort_member_time BEFORE INSERT OR UPDATE ON csi_cohort_members
 FOR EACH ROW EXECUTE FUNCTION check_csi_cohort_member_time();

-- Header описывает snapshot принятого набора; изменение истории не является
-- reconciliation. Для нового набора нужен новый dataset_code/собственные CSI IDs.
CREATE OR REPLACE FUNCTION immutable_csi_cohort_snapshot() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW IS DISTINCT FROM OLD THEN
    RAISE EXCEPTION 'CSI cohort snapshot is immutable' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS csi_cohort_immutable ON csi_cohorts;
CREATE TRIGGER csi_cohort_immutable BEFORE UPDATE ON csi_cohorts
 FOR EACH ROW EXECUTE FUNCTION immutable_csi_cohort_snapshot();
DROP TRIGGER IF EXISTS csi_cohort_visits_immutable ON csi_cohort_visits;
CREATE TRIGGER csi_cohort_visits_immutable BEFORE UPDATE ON csi_cohort_visits
 FOR EACH ROW EXECUTE FUNCTION immutable_csi_cohort_snapshot();
DROP TRIGGER IF EXISTS csi_cohort_members_immutable ON csi_cohort_members;
CREATE TRIGGER csi_cohort_members_immutable BEFORE UPDATE ON csi_cohort_members
 FOR EACH ROW EXECUTE FUNCTION immutable_csi_cohort_snapshot();

DROP TRIGGER IF EXISTS csi_cohorts_activity ON csi_cohorts;
CREATE TRIGGER csi_cohorts_activity AFTER INSERT OR UPDATE OR DELETE ON csi_cohorts
 FOR EACH ROW EXECUTE FUNCTION log_db_activity();
DROP TRIGGER IF EXISTS csi_cohort_visits_activity ON csi_cohort_visits;
CREATE TRIGGER csi_cohort_visits_activity AFTER INSERT OR UPDATE OR DELETE ON csi_cohort_visits
 FOR EACH ROW EXECUTE FUNCTION log_db_activity();
DROP TRIGGER IF EXISTS csi_cohort_members_activity ON csi_cohort_members;
CREATE TRIGGER csi_cohort_members_activity AFTER INSERT OR UPDATE OR DELETE ON csi_cohort_members
 FOR EACH ROW EXECUTE FUNCTION log_db_activity();
