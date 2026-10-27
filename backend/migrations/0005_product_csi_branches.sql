-- =============================================================================
-- CX Pulse Control — миграция 0005 «Кабинет, CSI, ВСП» (контракт v1.5, ТЗ 24–25, T-237)
-- Идемпотентна: на чистой БД после 0001+0004 — применяет изменения; повторный прогон — no-op.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- A. Продуктовые направления (ТЗ 24.2)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS product_lines (
  code              text PRIMARY KEY,
  name_ru           text NOT NULL,
  name_en           text NOT NULL,
  rate_code         text NOT NULL REFERENCES dcltv_rates(code),
  owner_team_code   text NOT NULL REFERENCES teams(code),
  owner_is_proxy    boolean NOT NULL DEFAULT false,
  product_codes     text[] NOT NULL DEFAULT '{}',
  sort_order        smallint NOT NULL DEFAULT 0
);
COMMENT ON TABLE product_lines IS '15 продуктовых направлений ЕТЗ; сид из data/product_lines.yaml (T-240)';

CREATE TABLE IF NOT EXISTS product_signal_history (
  id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  product_line_code   text NOT NULL REFERENCES product_lines(code),
  month               date NOT NULL,
  signal_count        integer NOT NULL DEFAULT 0,
  negative_count      integer NOT NULL DEFAULT 0,
  critical_count      integer NOT NULL DEFAULT 0,
  by_source           jsonb NOT NULL DEFAULT '{}'::jsonb,
  loss_rub            numeric(14, 2) NOT NULL DEFAULT 0,
  is_synthetic        boolean NOT NULL DEFAULT false,
  UNIQUE (product_line_code, month)
);
CREATE INDEX IF NOT EXISTS product_signal_history_line_month_idx ON product_signal_history (product_line_code, month DESC);

-- -----------------------------------------------------------------------------
-- B. Сигналы: направление, красные слова, флаги, meta (ТЗ 24.3)
-- -----------------------------------------------------------------------------
ALTER TABLE signals ADD COLUMN IF NOT EXISTS product_line_code text REFERENCES product_lines(code);
ALTER TABLE signals ADD COLUMN IF NOT EXISTS red_words text[] NOT NULL DEFAULT '{}';
ALTER TABLE signals ADD COLUMN IF NOT EXISTS flags text[] NOT NULL DEFAULT '{}';
ALTER TABLE signals ADD COLUMN IF NOT EXISTS meta jsonb NOT NULL DEFAULT '{}'::jsonb;
CREATE INDEX IF NOT EXISTS signals_product_line_idx ON signals (product_line_code) WHERE product_line_code IS NOT NULL;
CREATE INDEX IF NOT EXISTS signals_flags_gin_idx ON signals USING gin (flags);

ALTER TABLE regions ADD COLUMN IF NOT EXISTS okato text;

-- -----------------------------------------------------------------------------
-- C. Канал CSI (ТЗ 25)
-- -----------------------------------------------------------------------------
INSERT INTO channels (code, name_ru, name_en, identifies_client, is_public)
VALUES ('csi_survey', 'Опрос CSI', 'CSI survey', true, false)
ON CONFLICT (code) DO NOTHING;

CREATE TABLE IF NOT EXISTS csi_responses (
  signal_id            bigint PRIMARY KEY REFERENCES signals(id) ON DELETE CASCADE,
  csi_no               text NOT NULL UNIQUE,
  complaint_ru         text NOT NULL,
  ticket_code          text,
  waiting_count        smallint,
  serving_count        smallint,
  out_of_order_count   smallint,
  wait_min             numeric(8, 2),
  service_min          numeric(8, 2),
  redirects            smallint NOT NULL DEFAULT 0,
  products             text[] NOT NULL DEFAULT '{}',
  branch_id            integer REFERENCES branches(id),
  employee_id          bigint REFERENCES employees(id),
  position             text,
  education            text,
  tenure_position_days integer,
  tenure_org_days      integer,
  created_at           timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS csi_responses_branch_idx ON csi_responses (branch_id) WHERE branch_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS csi_responses_employee_idx ON csi_responses (employee_id) WHERE employee_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS csi_visits_agg (
  branch_id          integer NOT NULL REFERENCES branches(id),
  day                date NOT NULL,
  wait_bucket        text NOT NULL,
  redirects_bucket   text NOT NULL,
  visits             integer NOT NULL DEFAULT 0,
  PRIMARY KEY (branch_id, day, wait_bucket, redirects_bucket)
);

-- -----------------------------------------------------------------------------
-- D. Сеть ВСП (ТЗ 25.3)
-- -----------------------------------------------------------------------------
ALTER TABLE branches ADD COLUMN IF NOT EXISTS branch_type text CHECK (branch_type IS NULL OR branch_type IN ('flagship','standard','additional','mobile'));
ALTER TABLE branches ADD COLUMN IF NOT EXISTS branch_status text CHECK (branch_status IS NULL OR branch_status IN ('open','closed'));
ALTER TABLE branches ADD COLUMN IF NOT EXISTS lat numeric(9, 6);
ALTER TABLE branches ADD COLUMN IF NOT EXISTS lon numeric(9, 6);
ALTER TABLE branches ADD COLUMN IF NOT EXISTS address_ru text;
ALTER TABLE branches ADD COLUMN IF NOT EXISTS hours_ru text;
ALTER TABLE branches ADD COLUMN IF NOT EXISTS opened_sim timestamptz;
ALTER TABLE branches ADD COLUMN IF NOT EXISTS closed_sim timestamptz;
ALTER TABLE branches ADD COLUMN IF NOT EXISTS product_line_codes text[] NOT NULL DEFAULT '{}';

ALTER TABLE employees ADD COLUMN IF NOT EXISTS education text;
ALTER TABLE employees ADD COLUMN IF NOT EXISTS position_since_sim timestamptz;

CREATE TABLE IF NOT EXISTS branch_network_history (
  id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  month            date NOT NULL,
  region_code      text NOT NULL REFERENCES regions(code),
  open_count       integer NOT NULL DEFAULT 0,
  closed_count     integer NOT NULL DEFAULT 0,
  opened_in_month  integer NOT NULL DEFAULT 0,
  closed_in_month  integer NOT NULL DEFAULT 0,
  UNIQUE (month, region_code)
);
CREATE INDEX IF NOT EXISTS branch_network_history_region_month_idx ON branch_network_history (region_code, month DESC);

-- -----------------------------------------------------------------------------
-- E. Представления ЕТЗ (ТЗ 24.3, 24.5)
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_signal_normalized AS
SELECT
  s.id AS signal_id,
  s.public_id,
  s.run_id,
  s.channel_code AS channel,
  cl.public_id AS client_id,
  s.text,
  s.received_sim AS event_timestamp,
  jsonb_build_object(
    'region_okato', r.okato,
    'region_code', COALESCE(s.geo->>'region_code', cl.region_code::text),
    'vsp_code', br.code
  ) AS geo,
  COALESCE(s.product_line_code, s.classification->>'product_line') AS product_line,
  s.classification->>'product' AS product,
  s.classification->>'signal_type' AS topic,
  s.classification->'problem_summary'->>'problem' AS subtopic,
  s.sentiment,
  s.classification->>'signal_level' AS signal_level,
  s.meta->>'source_url' AS source_url,
  s.meta->'csi_meta' AS csi_meta,
  s.red_words,
  s.flags
FROM signals s
LEFT JOIN clients cl ON cl.id = s.client_id
LEFT JOIN regions r ON r.code = COALESCE(s.geo->>'region_code', cl.region_code::text)
LEFT JOIN csi_responses cr ON cr.signal_id = s.id
LEFT JOIN branches br ON br.id = cr.branch_id;

CREATE OR REPLACE VIEW v_cabinet_kpi AS
SELECT
  pl.code AS product_line_code,
  pl.name_ru,
  pl.name_en,
  pl.owner_team_code,
  count(s.id) FILTER (WHERE s.id IS NOT NULL) AS signal_count,
  count(s.id) FILTER (WHERE s.sentiment = 'negative') AS negative_count,
  count(s.id) FILTER (WHERE (s.classification->>'criticality') = 'high') AS critical_count,
  coalesce(sum(ie.prevented_loss_rub), 0) AS prevented_loss_rub,
  coalesce(sum(ie.potential_loss_rub), 0) AS potential_loss_rub
FROM product_lines pl
LEFT JOIN signals s ON s.product_line_code = pl.code
LEFT JOIN incident_signals isg ON isg.signal_id = s.id
LEFT JOIN incident_economics ie ON ie.incident_id = isg.incident_id
GROUP BY pl.code, pl.name_ru, pl.name_en, pl.owner_team_code;

-- -----------------------------------------------------------------------------
-- F. Журнал активности БД
-- -----------------------------------------------------------------------------
DROP TRIGGER IF EXISTS product_lines_activity ON product_lines;
CREATE TRIGGER product_lines_activity AFTER INSERT OR UPDATE OR DELETE ON product_lines FOR EACH ROW EXECUTE FUNCTION log_db_activity();
DROP TRIGGER IF EXISTS product_signal_history_activity ON product_signal_history;
CREATE TRIGGER product_signal_history_activity AFTER INSERT OR UPDATE OR DELETE ON product_signal_history FOR EACH ROW EXECUTE FUNCTION log_db_activity();
DROP TRIGGER IF EXISTS csi_responses_activity ON csi_responses;
CREATE TRIGGER csi_responses_activity AFTER INSERT OR UPDATE OR DELETE ON csi_responses FOR EACH ROW EXECUTE FUNCTION log_db_activity();
DROP TRIGGER IF EXISTS csi_visits_agg_activity ON csi_visits_agg;
CREATE TRIGGER csi_visits_agg_activity AFTER INSERT OR UPDATE OR DELETE ON csi_visits_agg FOR EACH ROW EXECUTE FUNCTION log_db_activity();
DROP TRIGGER IF EXISTS branch_network_history_activity ON branch_network_history;
CREATE TRIGGER branch_network_history_activity AFTER INSERT OR UPDATE OR DELETE ON branch_network_history FOR EACH ROW EXECUTE FUNCTION log_db_activity();
