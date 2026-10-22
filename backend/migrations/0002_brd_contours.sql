-- =============================================================================
-- CX Pulse Control — миграция 0002 «Контуры BRD демо-стенда» (контракт v1.3, ТЗ 3.4, 4.7, 9.6, 13, 21–23)
-- Идемпотентна: на чистой БД после 0001 (который исполняет актуальный schema.sql v1.3) все выражения — no-op;
-- на БД v1.2 — добавляет колонки, расширяет CHECK-перечисления, создаёт новые таблицы, представления и триггеры.
-- Исполняется alembic-ревизией 0002_brd_contours (op.execute этого файла).
-- =============================================================================

-- -----------------------------------------------------------------------------
-- A. Расширение перечислений (CHECK) существующих таблиц
-- -----------------------------------------------------------------------------
ALTER TABLE sim_runs DROP CONSTRAINT IF EXISTS sim_runs_kind_check;
ALTER TABLE sim_runs ADD CONSTRAINT sim_runs_kind_check CHECK (kind IN ('baseline','free','scenario','live'));

ALTER TABLE incidents DROP CONSTRAINT IF EXISTS incidents_incident_type_check;
ALTER TABLE incidents ADD CONSTRAINT incidents_incident_type_check CHECK (incident_type IN ('tech_fault','client_error','tariff_terms','service_quality','fraud_suspicion','legal_regulatory','info_request','suggestion','account_closure','proactive','fee_refund','misselling'));
ALTER TABLE incidents DROP CONSTRAINT IF EXISTS incidents_complexity_check;
ALTER TABLE incidents ADD CONSTRAINT incidents_complexity_check CHECK (complexity IN ('instant','easy','medium','hard'));
ALTER TABLE incidents DROP CONSTRAINT IF EXISTS incidents_created_by_check;
ALTER TABLE incidents ADD CONSTRAINT incidents_created_by_check CHECK (created_by IN ('agent','human','team','behavior_model','scenario','compliance'));

ALTER TABLE signals DROP CONSTRAINT IF EXISTS signals_origin_check;
ALTER TABLE signals ADD CONSTRAINT signals_origin_check CHECK (origin IN ('sim','scenario','jury','landing','telegram_bot','proactive','twin','review_portal','voice_input','api'));

ALTER TABLE agent_runs DROP CONSTRAINT IF EXISTS agent_runs_kind_check;
ALTER TABLE agent_runs ADD CONSTRAINT agent_runs_kind_check CHECK (kind IN ('agent','client_twin','team_emulator','bench','compare','compliance_detector','speaker_attribution'));

-- -----------------------------------------------------------------------------
-- B. Новые колонки существующих таблиц
-- -----------------------------------------------------------------------------
ALTER TABLE clients         ADD COLUMN IF NOT EXISTS social_handles jsonb NOT NULL DEFAULT '{}'::jsonb;   -- {review_portal:'@user_1234', telegram:'@tg_1234'} — синтетика
ALTER TABLE clients         ADD COLUMN IF NOT EXISTS refunds_30d    smallint NOT NULL DEFAULT 0;         -- политика антизлоупотребления (ТЗ 9.3)
ALTER TABLE client_products ADD COLUMN IF NOT EXISTS card_last4     char(4);                             -- из невалидного по Луну номера
ALTER TABLE operations      ADD COLUMN IF NOT EXISTS method         text CHECK (method IN ('qr_sbp','card','transfer','cash','online'));
ALTER TABLE operations      ADD COLUMN IF NOT EXISTS merchant       text;
ALTER TABLE operations      ADD COLUMN IF NOT EXISTS fee_amount     numeric(14,2) NOT NULL DEFAULT 0;
ALTER TABLE signals         ADD COLUMN IF NOT EXISTS voice_meta     jsonb;                               -- {stt_provider, transcript_raw, avg_confidence, duration_ms, latency_ms}
ALTER TABLE signals         ADD COLUMN IF NOT EXISTS external_post_id bigint;                            -- FK ниже, после external_posts
ALTER TABLE economics_settings ADD COLUMN IF NOT EXISTS misselling_case_cost_rub integer NOT NULL DEFAULT 4050; -- ТЗ 14.4, уточнение 20.3 п. 1
ALTER TABLE incident_economics ADD COLUMN IF NOT EXISTS refund_amount_rub numeric(14,2) NOT NULL DEFAULT 0; -- прямая стоимость возврата (fee_refund)
CREATE INDEX IF NOT EXISTS clients_social_idx ON clients USING gin (social_handles);
CREATE INDEX IF NOT EXISTS client_products_last4_idx ON client_products (card_last4) WHERE card_last4 IS NOT NULL;
CREATE INDEX IF NOT EXISTS operations_method_fee_idx ON operations (method) WHERE fee_amount > 0;

-- -----------------------------------------------------------------------------
-- C. Mock-АБС: счета, тарифы, проводки (ТЗ 3.4, 21.4)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS accounts (
  id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  client_id      bigint NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  product_id     bigint REFERENCES client_products(id) ON DELETE SET NULL,
  number_masked  text NOT NULL,                       -- '408** **** 1234'
  currency       char(3) NOT NULL DEFAULT 'RUB',
  balance        numeric(14,2) NOT NULL DEFAULT 0,
  status         text NOT NULL DEFAULT 'active' CHECK (status IN ('active','blocked','closed')),
  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE accounts IS 'Mock-АБС: счета клиентов; баланс = сумма проводок (проверяется тестом)';
CREATE INDEX IF NOT EXISTS accounts_client_idx ON accounts (client_id);
DROP TRIGGER IF EXISTS accounts_updated ON accounts;
CREATE TRIGGER accounts_updated BEFORE UPDATE ON accounts FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE IF NOT EXISTS tariffs (
  id              integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  product_code    text NOT NULL REFERENCES products(code),
  operation_kind  text NOT NULL,                      -- payment, transfer, withdrawal, …
  method          text NOT NULL CHECK (method IN ('qr_sbp','card','transfer','cash','online','any')),
  fee_pct         numeric(6,4) NOT NULL DEFAULT 0,
  fee_fixed       numeric(14,2) NOT NULL DEFAULT 0,
  free_limit_rub  numeric(14,2),                      -- бесплатно до лимита в месяц
  note_ru         text,
  UNIQUE (product_code, operation_kind, method)
);
COMMENT ON TABLE tariffs IS 'Тарифы Mock-АБС; QR/СБП для физлиц — 0 ₽ (основание правила RULE-QR-FEE-001)';

CREATE TABLE IF NOT EXISTS ledger_entries (
  id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id              bigint NOT NULL REFERENCES sim_runs(id) ON DELETE CASCADE,
  account_id          bigint NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  operation_id        bigint REFERENCES operations(id) ON DELETE SET NULL,
  kind                text NOT NULL CHECK (kind IN ('debit','credit','fee','refund','reversal')),
  amount              numeric(14,2) NOT NULL CHECK (amount >= 0),
  counterpart         text,                           -- мерчант/контрагент (вымышленный)
  posted_at           timestamptz NOT NULL DEFAULT now(),
  posted_sim          timestamptz NOT NULL,
  correlation_id      uuid NOT NULL UNIQUE,           -- идемпотентность refund_fee
  refund_of_entry_id  bigint REFERENCES ledger_entries(id),
  rule_id             text,                           -- business_rules.code, если проводка создана по правилу
  agent_run_id        bigint REFERENCES agent_runs(id),
  created_by          text NOT NULL DEFAULT 'sim' CHECK (created_by IN ('sim','agent','human','scenario'))
);
COMMENT ON TABLE ledger_entries IS 'Проводки Mock-АБС; fee — комиссия, refund — возврат (всегда ссылается на исходную fee)';
CREATE INDEX IF NOT EXISTS ledger_account_idx ON ledger_entries (account_id, posted_sim DESC);
CREATE INDEX IF NOT EXISTS ledger_operation_idx ON ledger_entries (operation_id);
CREATE INDEX IF NOT EXISTS ledger_run_idx ON ledger_entries (run_id);
DROP TRIGGER IF EXISTS ledger_entries_activity ON ledger_entries;
CREATE TRIGGER ledger_entries_activity AFTER INSERT ON ledger_entries FOR EACH ROW EXECUTE FUNCTION log_db_activity();

-- -----------------------------------------------------------------------------
-- D. Детерминированные бизнес-правила (ТЗ 9.6)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS business_rules (
  code            text PRIMARY KEY,                   -- RULE-QR-FEE-001
  name_ru         text NOT NULL,
  name_en         text NOT NULL,
  condition       jsonb NOT NULL,                     -- contracts/events/rules/rule_condition.schema.json (JSON-логика)
  action          text NOT NULL CHECK (action IN ('refund_fee','propose_hitl','notify_only','suppress_duplicates')),
  limits          jsonb NOT NULL DEFAULT '{}'::jsonb, -- {max_amount_rub, requires_rule_confirmation:true}
  owner_team_code text NOT NULL REFERENCES teams(code),
  error_code      text REFERENCES error_codes(code),  -- дефект, который открывается команде-владельцу
  is_active       boolean NOT NULL DEFAULT true,
  version         integer NOT NULL DEFAULT 1,
  updated_at      timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE business_rules IS 'Детерминированные правила узла check_rules; деньги двигаются только при matched';
DROP TRIGGER IF EXISTS business_rules_updated ON business_rules;
CREATE TRIGGER business_rules_updated BEFORE UPDATE ON business_rules FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE IF NOT EXISTS rule_evaluations (
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id        bigint NOT NULL REFERENCES sim_runs(id) ON DELETE CASCADE,
  signal_id     bigint REFERENCES signals(id) ON DELETE CASCADE,
  agent_run_id  bigint REFERENCES agent_runs(id) ON DELETE CASCADE,
  rule_code     text NOT NULL REFERENCES business_rules(code),
  rule_version  integer NOT NULL,
  result        text NOT NULL CHECK (result IN ('matched','not_matched','error')),
  evidence      jsonb NOT NULL DEFAULT '{}'::jsonb,   -- {operation_ids:[], ledger_entry_ids:[], tariff_id, amount_rub}
  proposed_action text,
  amount_rub    numeric(14,2),
  latency_ms    integer NOT NULL DEFAULT 0,
  created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS rule_evaluations_signal_idx ON rule_evaluations (signal_id);
CREATE INDEX IF NOT EXISTS rule_evaluations_run_idx ON rule_evaluations (run_id);

-- -----------------------------------------------------------------------------
-- E. Внешние площадки: посты и публичные ответы (ТЗ 21.2, 21.5)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS external_posts (
  id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id           bigint NOT NULL REFERENCES sim_runs(id) ON DELETE CASCADE,
  public_id        text GENERATED ALWAYS AS ('POST-' || lpad(id::text, 6, '0')) STORED,
  platform         text NOT NULL CHECK (platform IN ('review_portal','telegram_channel')),
  author_nick      text NOT NULL,                     -- синтетический ник
  author_client_id bigint REFERENCES clients(id),     -- после матчинга
  match_confidence numeric(4,3),
  text             text NOT NULL,
  mentions         jsonb NOT NULL DEFAULT '{}'::jsonb, -- {card_last4, phone_masked, city}
  posted_at        timestamptz NOT NULL DEFAULT now(),
  posted_sim       timestamptz NOT NULL,
  reactions        integer NOT NULL DEFAULT 0,
  status           text NOT NULL DEFAULT 'new' CHECK (status IN ('new','processing','replied','escalated_to_dm','ignored')),
  signal_id        bigint REFERENCES signals(id),
  origin           text NOT NULL DEFAULT 'demo' CHECK (origin IN ('demo','api','background','scenario','telegram_bot')),
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE external_posts IS 'Эмулятор ленты отзовика/Telegram-канала (/feed); реальные площадки не парсятся';
CREATE INDEX IF NOT EXISTS external_posts_run_idx ON external_posts (run_id, posted_at DESC);
CREATE INDEX IF NOT EXISTS external_posts_status_idx ON external_posts (status);
DROP TRIGGER IF EXISTS external_posts_updated ON external_posts;
CREATE TRIGGER external_posts_updated BEFORE UPDATE ON external_posts FOR EACH ROW EXECUTE FUNCTION set_updated_at();
DROP TRIGGER IF EXISTS external_posts_activity ON external_posts;
CREATE TRIGGER external_posts_activity AFTER INSERT OR UPDATE ON external_posts FOR EACH ROW EXECUTE FUNCTION log_db_activity();
ALTER TABLE signals DROP CONSTRAINT IF EXISTS signals_external_post_fk;
ALTER TABLE signals ADD CONSTRAINT signals_external_post_fk FOREIGN KEY (external_post_id) REFERENCES external_posts(id);

CREATE TABLE IF NOT EXISTS external_replies (
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id        bigint NOT NULL REFERENCES sim_runs(id) ON DELETE CASCADE,
  post_id       bigint NOT NULL REFERENCES external_posts(id) ON DELETE CASCADE,
  incident_id   bigint REFERENCES incidents(id),
  agent_run_id  bigint REFERENCES agent_runs(id),
  author        text NOT NULL CHECK (author IN ('agent','human','client_twin')),
  text          text NOT NULL,
  published_at  timestamptz NOT NULL DEFAULT now(),
  latency_ms    integer,                              -- от posted_at поста до публикации (только для agent)
  llm_source    text CHECK (llm_source IN ('live','replay','mock'))
);
CREATE INDEX IF NOT EXISTS external_replies_post_idx ON external_replies (post_id, published_at);

-- -----------------------------------------------------------------------------
-- F. Отделения, сотрудники, аудиосессии, мисселлинг (ТЗ 22)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS branches (
  id          integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code        text NOT NULL UNIQUE,                   -- 'VSP-0042'
  name_ru     text NOT NULL,
  city_id     integer NOT NULL REFERENCES cities(id),
  region_code text NOT NULL REFERENCES regions(code),
  desks       smallint NOT NULL DEFAULT 6,
  manager_display_name text NOT NULL,                 -- руководитель отделения (синтетическое ФИО)
  manager_chat_id bigint                              -- Telegram руководителя для алертов (опционально)
);

CREATE TABLE IF NOT EXISTS employees (
  id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  public_id        text GENERATED ALWAYS AS ('EMP-' || lpad(id::text, 5, '0')) STORED,
  display_name     text NOT NULL,                     -- синтетическое ФИО
  branch_id        integer NOT NULL REFERENCES branches(id),
  desk_no          smallint NOT NULL,
  position         text NOT NULL DEFAULT 'client_manager',
  hired_sim        timestamptz,
  violations_count integer NOT NULL DEFAULT 0,
  is_active        boolean NOT NULL DEFAULT true
);
CREATE INDEX IF NOT EXISTS employees_branch_idx ON employees (branch_id);

CREATE TABLE IF NOT EXISTS misselling_patterns (
  code         text PRIMARY KEY,                      -- tie_in, substitution, concealment, pressure, guarantee
  name_ru      text NOT NULL,
  name_en      text NOT NULL,
  description_ru text NOT NULL,
  examples     text[] NOT NULL DEFAULT '{}',
  counter_examples text[] NOT NULL DEFAULT '{}',      -- что НЕ является нарушением
  keywords     text[] NOT NULL DEFAULT '{}',          -- для rule-детектора
  weight       numeric(4,2) NOT NULL DEFAULT 1,
  is_active    boolean NOT NULL DEFAULT true
);
COMMENT ON TABLE misselling_patterns IS 'Таксономия мисселлинга (ТЗ 22.4); по умолчанию активны tie_in, substitution, concealment';

CREATE TABLE IF NOT EXISTS audio_sessions (
  id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id           bigint NOT NULL REFERENCES sim_runs(id) ON DELETE CASCADE,
  public_id        text GENERATED ALWAYS AS ('AS-' || lpad(id::text, 6, '0')) STORED,
  branch_id        integer NOT NULL REFERENCES branches(id),
  employee_id      bigint NOT NULL REFERENCES employees(id),
  client_id        bigint REFERENCES clients(id),
  deal_product     text,                              -- 'ИСЖ', 'страховка к кредиту', …
  source           text NOT NULL CHECK (source IN ('mic','file','transcript')),
  stt_provider     text NOT NULL,                     -- vosk | browser | salutespeech | openai_compatible_audio | none
  stt_model        text,
  diarization_mode text NOT NULL CHECK (diarization_mode IN ('stereo','manual','auto')),
  status           text NOT NULL DEFAULT 'live' CHECK (status IN ('live','alerted','closed')),
  trigger_count    smallint NOT NULL DEFAULT 0,
  alert_threshold  smallint NOT NULL DEFAULT 3,
  incident_id      bigint REFERENCES incidents(id),
  demo_asset_id    bigint,                            -- FK ниже (demo_assets), если source = file|transcript
  started_at       timestamptz NOT NULL DEFAULT now(),
  started_sim      timestamptz NOT NULL,
  finished_at      timestamptz,
  store_audio      boolean NOT NULL DEFAULT false,    -- по умолчанию аудио не сохраняется (ТЗ 13)
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS audio_sessions_run_idx ON audio_sessions (run_id, started_at DESC);
CREATE INDEX IF NOT EXISTS audio_sessions_employee_idx ON audio_sessions (employee_id);
DROP TRIGGER IF EXISTS audio_sessions_updated ON audio_sessions;
CREATE TRIGGER audio_sessions_updated BEFORE UPDATE ON audio_sessions FOR EACH ROW EXECUTE FUNCTION set_updated_at();
DROP TRIGGER IF EXISTS audio_sessions_activity ON audio_sessions;
CREATE TRIGGER audio_sessions_activity AFTER INSERT OR UPDATE ON audio_sessions FOR EACH ROW EXECUTE FUNCTION log_db_activity();

CREATE TABLE IF NOT EXISTS utterances (
  id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  session_id         bigint NOT NULL REFERENCES audio_sessions(id) ON DELETE CASCADE,
  seq                integer NOT NULL,
  speaker            text NOT NULL CHECK (speaker IN ('employee','client','unknown')),
  speaker_confidence numeric(4,3) NOT NULL DEFAULT 1,
  speaker_source     text NOT NULL CHECK (speaker_source IN ('channel','manual','llm','transcript')),
  text               text NOT NULL,
  t0_ms              integer NOT NULL,
  t1_ms              integer NOT NULL,
  is_final           boolean NOT NULL DEFAULT true,
  stt_confidence     numeric(4,3),
  words              jsonb,                           -- [{w, t0, t1, conf}]
  latency_ms         integer,                         -- конец речи → финал
  created_at         timestamptz NOT NULL DEFAULT now(),
  UNIQUE (session_id, seq)
);
CREATE INDEX IF NOT EXISTS utterances_session_idx ON utterances (session_id, seq);

CREATE TABLE IF NOT EXISTS compliance_triggers (
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  session_id    bigint NOT NULL REFERENCES audio_sessions(id) ON DELETE CASCADE,
  utterance_id  bigint NOT NULL REFERENCES utterances(id) ON DELETE CASCADE,
  pattern_code  text NOT NULL REFERENCES misselling_patterns(code),
  confidence    numeric(4,3) NOT NULL,
  quote         text NOT NULL,
  explanation_ru text,
  detected_by   text NOT NULL CHECK (detected_by IN ('rules','llm','both')),
  status        text NOT NULL DEFAULT 'preliminary' CHECK (status IN ('preliminary','confirmed','dismissed')),
  agent_run_id  bigint REFERENCES agent_runs(id),    -- трассировка LLM-детектора (kind = compliance_detector)
  latency_ms    integer,                              -- финал реплики → статус
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now(),
  UNIQUE (utterance_id)                               -- не более одного триггера на реплику (ТЗ 22.4)
);
CREATE INDEX IF NOT EXISTS compliance_triggers_session_idx ON compliance_triggers (session_id);
DROP TRIGGER IF EXISTS compliance_triggers_updated ON compliance_triggers;
CREATE TRIGGER compliance_triggers_updated BEFORE UPDATE ON compliance_triggers FOR EACH ROW EXECUTE FUNCTION set_updated_at();
DROP TRIGGER IF EXISTS compliance_triggers_activity ON compliance_triggers;
CREATE TRIGGER compliance_triggers_activity AFTER INSERT OR UPDATE ON compliance_triggers FOR EACH ROW EXECUTE FUNCTION log_db_activity();

CREATE TABLE IF NOT EXISTS compliance_alerts (
  id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  session_id       bigint NOT NULL REFERENCES audio_sessions(id) ON DELETE CASCADE,
  incident_id      bigint REFERENCES incidents(id),
  sent_at          timestamptz NOT NULL DEFAULT now(),
  channels         text[] NOT NULL DEFAULT '{ws}',    -- ws, telegram
  latency_ms       integer,                           -- порог → отправка
  acknowledged_at  timestamptz,
  acknowledged_by  text,                              -- роль/имя (синтетическое)
  decision         text CHECK (decision IN ('go','false_positive','open_incident')),
  human_decision_id bigint REFERENCES human_decisions(id)
);
CREATE INDEX IF NOT EXISTS compliance_alerts_session_idx ON compliance_alerts (session_id);

CREATE TABLE IF NOT EXISTS stt_metrics (
  id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  session_id         bigint REFERENCES audio_sessions(id) ON DELETE CASCADE,
  provider           text NOT NULL,
  model              text,
  partial_latency_ms integer,
  final_latency_ms   integer,
  wer                numeric(5,4),                    -- только для source = file с эталоном
  cpu_ms             integer,
  audio_seconds      numeric(8,2),
  created_at         timestamptz NOT NULL DEFAULT now()
);

-- -----------------------------------------------------------------------------
-- G. Режим подстраховки: кассеты LLM и демо-активы (ТЗ 5.4, 12.7)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS llm_cassettes (
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  scenario_id   text,                                 -- scenarios.id или 'tests'
  request_hash  text NOT NULL,                        -- sha256(provider, model, normalized_messages, schema)
  provider      text NOT NULL,
  model         text NOT NULL,
  prompt_version text,
  response      jsonb NOT NULL,                       -- итоговый ответ (structured output / текст / tool calls)
  chunks        jsonb NOT NULL DEFAULT '[]'::jsonb,   -- [{delta, kind, at_ms}] для воспроизведения потока
  usage         jsonb NOT NULL DEFAULT '{}'::jsonb,
  recorded_at   timestamptz NOT NULL DEFAULT now(),
  UNIQUE (request_hash, model)
);
COMMENT ON TABLE llm_cassettes IS 'Записанные ответы реальных моделей для провайдера replay (честный офлайн-режим)';

CREATE TABLE IF NOT EXISTS demo_assets (
  id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  kind         text NOT NULL CHECK (kind IN ('audio','transcript','post','cassette')),
  scenario_id  text,
  title_ru     text NOT NULL,
  path         text NOT NULL,                         -- data/audio/scenario9_01.wav
  checksum     text NOT NULL,
  ref          jsonb,                                 -- эталонный транскрипт с ролями/таймкодами или текст поста
  duration_ms  integer
);
ALTER TABLE audio_sessions DROP CONSTRAINT IF EXISTS audio_sessions_demo_asset_fk;
ALTER TABLE audio_sessions ADD CONSTRAINT audio_sessions_demo_asset_fk FOREIGN KEY (demo_asset_id) REFERENCES demo_assets(id);

-- -----------------------------------------------------------------------------
-- H. Представления для живых контуров (ТЗ 14.1)
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_feed_latency AS
SELECT p.run_id,
       count(*)                                                                   AS posts,
       count(*) FILTER (WHERE p.status = 'replied')                               AS replied,
       count(*) FILTER (WHERE p.author_client_id IS NOT NULL)                     AS identified,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY r.latency_ms)                 AS reply_latency_p50_ms,
       percentile_cont(0.95) WITHIN GROUP (ORDER BY r.latency_ms)                AS reply_latency_p95_ms,
       coalesce(sum(l.amount) FILTER (WHERE l.kind = 'refund'), 0)                AS refunded_rub
FROM external_posts p
LEFT JOIN external_replies r ON r.post_id = p.id AND r.author = 'agent'
LEFT JOIN signals s ON s.id = p.signal_id
LEFT JOIN ledger_entries l ON l.operation_id = s.source_operation_id AND l.kind = 'refund' AND l.run_id = p.run_id
GROUP BY 1;

CREATE OR REPLACE VIEW v_compliance_by_employee AS
SELECT a.run_id,
       e.id AS employee_id, e.display_name, b.code AS branch_code, e.desk_no,
       count(DISTINCT a.id)                                                        AS sessions,
       count(t.id) FILTER (WHERE t.status = 'confirmed')                           AS triggers_confirmed,
       count(t.id) FILTER (WHERE t.status = 'dismissed')                           AS triggers_dismissed,
       count(DISTINCT al.id)                                                       AS alerts,
       count(DISTINCT al.id) FILTER (WHERE al.decision = 'false_positive')         AS false_alerts,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY t.latency_ms)                  AS trigger_latency_p50_ms
FROM audio_sessions a
JOIN employees e ON e.id = a.employee_id
JOIN branches b ON b.id = e.branch_id
LEFT JOIN compliance_triggers t ON t.session_id = a.id
LEFT JOIN compliance_alerts al ON al.session_id = a.id
GROUP BY 1,2,3,4,5;

-- Каналы NOTIFY, добавленные в v1.3: 'feed' (посты/ответы), 'abs' (проводки/балансы), 'compliance' (реплики/триггеры/алерты),
-- 'stt' (частичные результаты — публикуются напрямую из воркера, в БД не пишутся), 'demo' (failover).
