-- =============================================================================
-- CX Pulse Control — миграция 0003 «Дополнительное ТЗ» (контракт v1.4, ТЗ 3.7, 7, 9.7, 12.2, 13, 22.8–22.9)
-- Идемпотентна: на чистой БД после 0001 (schema.sql v1.4) все выражения — no-op; на БД v1.3 — применяет изменения.
-- Исполняется alembic-ревизией 0003_additional_tz (op.execute этого файла).
-- =============================================================================

-- -----------------------------------------------------------------------------
-- A. Перечисления (CHECK) существующих таблиц
-- -----------------------------------------------------------------------------
ALTER TABLE signals DROP CONSTRAINT IF EXISTS signals_origin_check;
ALTER TABLE signals ADD CONSTRAINT signals_origin_check CHECK (origin IN ('sim','scenario','jury','landing','telegram_bot','proactive','twin','review_portal','voice_input','api','transcript','polling'));

ALTER TABLE audio_sessions DROP CONSTRAINT IF EXISTS audio_sessions_source_check;
ALTER TABLE audio_sessions ADD CONSTRAINT audio_sessions_source_check CHECK (source IN ('mic','file','transcript'));

ALTER TABLE compliance_alerts DROP CONSTRAINT IF EXISTS compliance_alerts_decision_check;
ALTER TABLE compliance_alerts ADD CONSTRAINT compliance_alerts_decision_check CHECK (decision IN ('go','false_positive','open_incident','acknowledged'));

-- -----------------------------------------------------------------------------
-- B. Новые колонки существующих таблиц
-- -----------------------------------------------------------------------------
ALTER TABLE signals ADD COLUMN IF NOT EXISTS geo jsonb;                 -- {region_code, city_id, lat, lon, source: client_profile|message|contact|ip_mock|none} (ТЗ 3.7)
ALTER TABLE signals ADD COLUMN IF NOT EXISTS transcript_id bigint;      -- FK ниже (transcripts)
ALTER TABLE signals ADD COLUMN IF NOT EXISTS sentiment text CHECK (sentiment IN ('positive','neutral','negative')); -- внешняя метка ДТЗ FR-2.1 (дублирует classification->>'sentiment' для индексов)
CREATE INDEX IF NOT EXISTS signals_geo_region_idx ON signals ((geo->>'region_code'));
CREATE INDEX IF NOT EXISTS signals_sentiment_idx ON signals (sentiment);

ALTER TABLE incidents ADD COLUMN IF NOT EXISTS routing_status text NOT NULL DEFAULT 'pending' CHECK (routing_status IN ('pending','routed','escalated','clarification','rejected')); -- лента ДТЗ FR-5.3
ALTER TABLE incidents ADD COLUMN IF NOT EXISTS problem_summary jsonb;   -- {problem, severity, suggested_team} (ТЗ 7)

ALTER TABLE misselling_patterns ADD COLUMN IF NOT EXISTS family text NOT NULL DEFAULT 'misselling' CHECK (family IN ('misselling','conduct'));
ALTER TABLE misselling_patterns ADD COLUMN IF NOT EXISTS alert_policy text NOT NULL DEFAULT 'counter' CHECK (alert_policy IN ('counter','immediate','report'));
ALTER TABLE misselling_patterns ADD COLUMN IF NOT EXISTS immediate_threshold numeric(4,3) NOT NULL DEFAULT 0.8;
ALTER TABLE misselling_patterns ADD COLUMN IF NOT EXISTS recommendation_ru text;        -- шаблон рекомендации руководителю (ТЗ 22.9)
ALTER TABLE misselling_patterns ADD COLUMN IF NOT EXISTS training_module text;          -- код учебного модуля
COMMENT ON TABLE misselling_patterns IS 'Таксономия нарушений сотрудника: семейства misselling (ТЗ 22.4) и conduct — rudeness, script_violation, misinformation (ТЗ 22.8); имя таблицы сохранено для совместимости v1.3';

ALTER TABLE compliance_triggers ADD COLUMN IF NOT EXISTS recommendation_ru text;
ALTER TABLE compliance_triggers ADD COLUMN IF NOT EXISTS fact_check jsonb;              -- {claim, truth, source_table, source_key, verified}
ALTER TABLE compliance_alerts ADD COLUMN IF NOT EXISTS recommendation_ru text;
ALTER TABLE compliance_alerts ADD COLUMN IF NOT EXISTS kind text NOT NULL DEFAULT 'threshold' CHECK (kind IN ('threshold','immediate','report'));
ALTER TABLE compliance_alerts ADD COLUMN IF NOT EXISTS transcript_id bigint;            -- FK ниже
ALTER TABLE audio_sessions ADD COLUMN IF NOT EXISTS pacing text NOT NULL DEFAULT 'realtime' CHECK (pacing IN ('realtime','batch'));
ALTER TABLE audio_sessions ADD COLUMN IF NOT EXISTS transcript_id bigint;               -- FK ниже
ALTER TABLE audio_sessions ADD COLUMN IF NOT EXISTS report jsonb;                       -- transcript_report (ТЗ 22.8) для pacing = batch

ALTER TABLE economics_settings ADD COLUMN IF NOT EXISTS map_zone_thresholds jsonb NOT NULL DEFAULT '{"yellow":0.25,"red":0.5,"copilot_weight":0.5,"window_sim_hours":24}'::jsonb; -- ТЗ 12.2, уточнение 20.3 п. 7

-- -----------------------------------------------------------------------------
-- C. Приёмный слой ingest (ТЗ 3.7)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ingest_sources (
  code            text PRIMARY KEY,                   -- mock_social_polling, rest_default, file_import
  kind            text NOT NULL CHECK (kind IN ('rest','polling','file')),
  channel_code    text NOT NULL REFERENCES channels(code),
  config          jsonb NOT NULL DEFAULT '{}'::jsonb, -- polling: {url, headers?, auth_env?}; file: {path, pattern}
  enabled         boolean NOT NULL DEFAULT true,
  interval_s      integer NOT NULL DEFAULT 10 CHECK (interval_s >= 5),
  last_polled_at  timestamptz,
  cursor          text,
  stats           jsonb NOT NULL DEFAULT '{}'::jsonb, -- {polls, accepted, duplicates, rejected, last_error}
  is_external     boolean NOT NULL DEFAULT false,     -- true = URL вне стенда (бейдж «внешний источник»)
  updated_at      timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE ingest_sources IS 'Адаптеры источников сообщений (ДТЗ FR-1.2): REST, polling, файлы';
DROP TRIGGER IF EXISTS ingest_sources_updated ON ingest_sources;
CREATE TRIGGER ingest_sources_updated BEFORE UPDATE ON ingest_sources FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE IF NOT EXISTS transcripts (
  id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id           bigint NOT NULL REFERENCES sim_runs(id) ON DELETE CASCADE,
  public_id        text GENERATED ALWAYS AS ('TR-' || lpad(id::text, 6, '0')) STORED,
  kind             text NOT NULL CHECK (kind IN ('branch_retail','contact_center_call','contact_center_chat')),
  source           text NOT NULL CHECK (source IN ('api','file','import','scenario')),
  filename         text,
  format           text NOT NULL CHECK (format IN ('json','txt')),
  branch_id        integer REFERENCES branches(id),
  employee_id      bigint REFERENCES employees(id),
  client_id        bigint REFERENCES clients(id),
  contact_hints    jsonb,                              -- {phone, email, nickname, card_last4, name}
  deal_product     text,
  started_at       timestamptz,
  geo              jsonb,
  turns            jsonb NOT NULL,                     -- [{seq, speaker, text, t0_ms, t1_ms}] по ingest/transcript.schema.json
  turns_count      integer NOT NULL DEFAULT 0,
  analyses         text[] NOT NULL DEFAULT '{client_signal,employee_quality}', -- какие анализы запрошены
  status           text NOT NULL DEFAULT 'received' CHECK (status IN ('received','analyzing','done','failed')),
  signal_id        bigint REFERENCES signals(id),      -- сигнал клиента (анализ client_signal)
  audio_session_id bigint REFERENCES audio_sessions(id), -- пакетная сессия (анализ employee_quality)
  report           jsonb,                              -- краткая сводка обоих анализов для вкладки «Транскрипты»
  error            text,
  received_at      timestamptz NOT NULL DEFAULT now(),
  received_sim     timestamptz NOT NULL,
  analyzed_at      timestamptz,
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE transcripts IS 'Готовые текстовые транскрипты диалогов (ДТЗ FR-1.1, FR-4.1): JSON/TXT файлами и по REST';
CREATE INDEX IF NOT EXISTS transcripts_run_idx ON transcripts (run_id, received_at DESC);
CREATE INDEX IF NOT EXISTS transcripts_status_idx ON transcripts (status);
CREATE INDEX IF NOT EXISTS transcripts_employee_idx ON transcripts (employee_id);
DROP TRIGGER IF EXISTS transcripts_updated ON transcripts;
CREATE TRIGGER transcripts_updated BEFORE UPDATE ON transcripts FOR EACH ROW EXECUTE FUNCTION set_updated_at();
DROP TRIGGER IF EXISTS transcripts_activity ON transcripts;
CREATE TRIGGER transcripts_activity AFTER INSERT OR UPDATE ON transcripts FOR EACH ROW EXECUTE FUNCTION log_db_activity();

ALTER TABLE signals DROP CONSTRAINT IF EXISTS signals_transcript_fk;
ALTER TABLE signals ADD CONSTRAINT signals_transcript_fk FOREIGN KEY (transcript_id) REFERENCES transcripts(id);
ALTER TABLE audio_sessions DROP CONSTRAINT IF EXISTS audio_sessions_transcript_fk;
ALTER TABLE audio_sessions ADD CONSTRAINT audio_sessions_transcript_fk FOREIGN KEY (transcript_id) REFERENCES transcripts(id);
ALTER TABLE compliance_alerts DROP CONSTRAINT IF EXISTS compliance_alerts_transcript_fk;
ALTER TABLE compliance_alerts ADD CONSTRAINT compliance_alerts_transcript_fk FOREIGN KEY (transcript_id) REFERENCES transcripts(id);

CREATE TABLE IF NOT EXISTS ingest_messages (
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id        bigint NOT NULL REFERENCES sim_runs(id) ON DELETE CASCADE,
  source_code   text NOT NULL REFERENCES ingest_sources(code),
  external_id   text NOT NULL,
  payload       jsonb NOT NULL,                        -- единая схема ingest/unified_message.schema.json
  received_at   timestamptz NOT NULL DEFAULT now(),
  status        text NOT NULL CHECK (status IN ('accepted','duplicate','rejected')),
  signal_id     bigint REFERENCES signals(id),
  error         text,
  UNIQUE (source_code, external_id)
);
COMMENT ON TABLE ingest_messages IS 'Журнал приёма сообщений адаптерами: идемпотентность по external_id (ДТЗ FR-1.2–1.3)';
CREATE INDEX IF NOT EXISTS ingest_messages_run_idx ON ingest_messages (run_id, received_at DESC);

-- -----------------------------------------------------------------------------
-- D. Эскалации и тикетница (ТЗ 9.7)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS escalations (
  id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id           bigint NOT NULL REFERENCES sim_runs(id) ON DELETE CASCADE,
  public_id        text GENERATED ALWAYS AS ('ESC-' || lpad(id::text, 6, '0')) STORED,
  incident_id      bigint REFERENCES incidents(id) ON DELETE SET NULL,
  signal_id        bigint REFERENCES signals(id) ON DELETE SET NULL,
  reason           text NOT NULL,
  severity         text NOT NULL CHECK (severity IN ('low','medium','high','critical')),
  to_role          text NOT NULL CHECK (to_role IN ('cx_lead','branch_manager')),
  status           text NOT NULL DEFAULT 'open' CHECK (status IN ('open','acknowledged','resolved','dismissed')),
  created_by       text NOT NULL CHECK (created_by IN ('agent','human','compliance')),
  agent_run_id     bigint REFERENCES agent_runs(id),
  human_decision_id bigint REFERENCES human_decisions(id),
  acknowledged_by  text,
  acknowledged_at  timestamptz,
  resolution_ru    text,
  created_sim      timestamptz NOT NULL,
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE escalations IS 'Эскалации руководителю (ДТЗ FR-3.4): создаются инструментом escalate_to_manager или человеком';
CREATE INDEX IF NOT EXISTS escalations_run_idx ON escalations (run_id, created_at DESC);
CREATE INDEX IF NOT EXISTS escalations_status_idx ON escalations (status);
DROP TRIGGER IF EXISTS escalations_updated ON escalations;
CREATE TRIGGER escalations_updated BEFORE UPDATE ON escalations FOR EACH ROW EXECUTE FUNCTION set_updated_at();
DROP TRIGGER IF EXISTS escalations_activity ON escalations;
CREATE TRIGGER escalations_activity AFTER INSERT OR UPDATE ON escalations FOR EACH ROW EXECUTE FUNCTION log_db_activity();

CREATE TABLE IF NOT EXISTS service_scripts (
  code        text PRIMARY KEY,                        -- retail_service_v1
  kind        text NOT NULL CHECK (kind IN ('retail_service','retail_sales','contact_center')),
  name_ru     text NOT NULL,
  steps       jsonb NOT NULL,                          -- [{code, name_ru, required, markers[], forbidden_phrases[]}]
  version     integer NOT NULL DEFAULT 1,
  is_active   boolean NOT NULL DEFAULT true,
  updated_at  timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE service_scripts IS 'Эталонные скрипты обслуживания для проверки script_violation (ТЗ 22.8)';
DROP TRIGGER IF EXISTS service_scripts_updated ON service_scripts;
CREATE TRIGGER service_scripts_updated BEFORE UPDATE ON service_scripts FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- -----------------------------------------------------------------------------
-- E. Представления: тикетница и зоны карты (ТЗ 9.7, 12.2)
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_tickets AS
SELECT i.id                               AS incident_id,
       i.public_id                        AS ticket_id,
       i.run_id,
       i.team_code                        AS department,
       i.priority,
       coalesce(i.problem_summary->>'problem', i.title) AS summary,
       i.problem_summary->>'severity'     AS severity,
       CASE i.status
         WHEN 'new' THEN 'open' WHEN 'classified' THEN 'open' WHEN 'routed' THEN 'open'
         WHEN 'in_progress' THEN 'in_progress' WHEN 'fix_proposed' THEN 'in_progress' WHEN 'fix_deployed' THEN 'in_progress'
         WHEN 'awaiting_human' THEN 'in_progress' WHEN 'awaiting_client' THEN 'in_progress' WHEN 'escalated' THEN 'in_progress'
         WHEN 'resolved' THEN 'resolved' WHEN 'verifying' THEN 'resolved'
         WHEN 'closed' THEN 'closed' WHEN 'rejected' THEN 'rejected' WHEN 'duplicate' THEN 'rejected'
         ELSE 'open' END                  AS status,
       i.status                           AS incident_status,
       i.routing_status,
       s.channel_code                     AS channel,
       s.sentiment,
       c.segment_code                     AS client_segment,
       i.region_code,
       i.created_sim                      AS created_at,
       EXISTS (SELECT 1 FROM escalations e WHERE e.incident_id = i.id AND e.status IN ('open','acknowledged')) AS escalated,
       i.agent_run_id
FROM incidents i
LEFT JOIN LATERAL (
  SELECT sg.channel_code, sg.sentiment
  FROM incident_signals isg JOIN signals sg ON sg.id = isg.signal_id
  WHERE isg.incident_id = i.id ORDER BY (isg.link_type = 'primary') DESC, isg.linked_sim LIMIT 1
) s ON true
LEFT JOIN clients c ON c.id = i.primary_client_id;

CREATE OR REPLACE VIEW v_map_zones AS
WITH st AS (
  SELECT (SELECT map_zone_thresholds FROM economics_settings WHERE id = 1) AS t
), sig AS (
  SELECT s.run_id, s.geo->>'region_code' AS region_code,
         count(*) AS total,
         count(*) FILTER (WHERE s.sentiment = 'negative') AS negative,
         count(*) FILTER (WHERE (s.classification->>'criticality') = 'high') AS critical_signals
  FROM signals s, st
  WHERE s.geo->>'region_code' IS NOT NULL
    AND s.received_sim >= (SELECT max(received_sim) FROM signals) - make_interval(hours => (st.t->>'window_sim_hours')::int)
  GROUP BY 1,2
), cop AS (
  SELECT a.run_id, b.region_code,
         count(DISTINCT a.id) AS sessions,
         count(t.id) FILTER (WHERE t.status = 'confirmed') AS triggers,
         count(DISTINCT al.id) FILTER (WHERE al.kind IN ('threshold','immediate')) AS alerts
  FROM audio_sessions a
  JOIN employees e ON e.id = a.employee_id
  JOIN branches b ON b.id = e.branch_id
  LEFT JOIN compliance_triggers t ON t.session_id = a.id
  LEFT JOIN compliance_alerts al ON al.session_id = a.id
  GROUP BY 1,2
), inc AS (
  SELECT run_id, region_code, count(*) AS critical_incidents
  FROM incidents WHERE criticality = 'high' AND status NOT IN ('closed','rejected') AND region_code IS NOT NULL
  GROUP BY 1,2
), base AS (
  SELECT coalesce(sig.run_id, cop.run_id, inc.run_id) AS run_id,
         coalesce(sig.region_code, cop.region_code, inc.region_code) AS region_code,
         coalesce(sig.total,0) AS signals_total,
         CASE WHEN coalesce(sig.total,0) > 0 THEN sig.negative::numeric / sig.total ELSE 0 END AS negativity_index,
         CASE WHEN coalesce(cop.sessions,0) > 0 THEN least(1, (cop.triggers::numeric / 3 + cop.alerts) / cop.sessions) ELSE 0 END AS copilot_index,
         coalesce(inc.critical_incidents,0) + coalesce(cop.alerts,0) AS critical_count
  FROM sig FULL JOIN cop ON cop.run_id = sig.run_id AND cop.region_code = sig.region_code
           FULL JOIN inc ON inc.run_id = coalesce(sig.run_id, cop.run_id) AND inc.region_code = coalesce(sig.region_code, cop.region_code)
)
SELECT b.run_id, b.region_code, b.signals_total,
       round(b.negativity_index, 3) AS negativity_index,
       round(b.copilot_index, 3)    AS copilot_index,
       b.critical_count,
       round(least(1, b.negativity_index + (st.t->>'copilot_weight')::numeric * b.copilot_index), 3) AS zone_index,
       CASE WHEN b.critical_count > 0 OR b.negativity_index + (st.t->>'copilot_weight')::numeric * b.copilot_index >= (st.t->>'red')::numeric THEN 'red'
            WHEN b.negativity_index + (st.t->>'copilot_weight')::numeric * b.copilot_index >= (st.t->>'yellow')::numeric THEN 'yellow'
            ELSE 'green' END AS zone,
       now() AS computed_at
FROM base b, st;

-- Каналы NOTIFY, добавленные в v1.4: 'ingest' (транскрипты/сообщения адаптеров), 'escalations', 'tickets' (= incidents, алиас для вкладки «Тикеты»), 'zones' (пересчёт зон карты).
