-- =============================================================================
-- CX Pulse Control — схема PostgreSQL 16 (контракт v1.4, соответствует ТЗ разделы 3.4, 3.7, 4.5–4.7, 8, 9.6–9.7, 13, 14, 21–22)
-- v1.2: таблица sim_runs и колонка run_id во всех таблицах данных, порождаемых симулятором/агентом (ТЗ 4.6).
-- v1.3: контуры BRD демо-стенда — Mock-АБС (accounts, tariffs, ledger_entries), бизнес-правила, внешние площадки,
--       отделения/аудиосессии/мисселлинг, кассеты replay; расширены CHECK-перечисления и колонки clients/operations/signals.
--       Для БД, созданных по v1.2, те же изменения применяет идемпотентная миграция 0002 (contracts/db/migrations/0002_brd_contours.sql).
-- v1.4: дополнительное ТЗ — приёмный слой (ingest_sources, ingest_messages, transcripts, signals.geo/sentiment), эскалации и тикетница
--       (escalations, v_tickets), семейство conduct в таксономии нарушений, service_scripts, пакетные сессии, зоны карты (v_map_zones).
--       Для БД v1.3 — идемпотентная миграция 0003 (contracts/db/migrations/0003_additional_tz.sql).
-- v1.5: след и поиск — public_id, pg_trgm, FTS (0004); кабинет/CSI/ВСП — product_lines, csi_*, branch_network_history,
--       v_signal_normalized, v_cabinet_kpi (contracts/db/migrations/0005_product_csi_branches.sql); миграции 0004–0005 идемпотентны.
-- Правила: snake_case; все суффиксы *_at — реальное время (timestamptz);
-- все *_sim — симуляционное время (timestamptz, календарь симулятора);
-- JSONB для гибких полей с описанием структуры в contracts/events/*.schema.json.
-- Никаких реальных ПДн: display_name/contacts генерируются синтетически (см. ТЗ 13).
-- Запуск: применяется миграцией alembic 0001_initial_schema (op.execute этого файла); 0002_brd_contours — no-op на свежей БД.
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;      -- gen_random_uuid(), шифрование ключей LLM
CREATE EXTENSION IF NOT EXISTS pg_trgm;     -- поиск по public_id и подсказкам (ТЗ 28.2, миграция 0004)
-- CREATE EXTENSION IF NOT EXISTS vector;     -- опционально (pgvector) для search_similar_signals

-- -----------------------------------------------------------------------------
-- 0. Служебные функции
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END $$;

-- Лог изменений для экрана «Данные в БД» (ТЗ 12.2 экран 4d). Пишется триггерами на ключевых таблицах.
CREATE TABLE db_activity_log (
  id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id      bigint,                                 -- снимок запуска: сохраняется и после DELETE
  table_name  text        NOT NULL,
  op          text        NOT NULL CHECK (op IN ('INSERT','UPDATE','DELETE')),
  pk          text        NOT NULL,
  summary     jsonb,                                  -- короткая выжимка изменённых полей
  ts          timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE db_activity_log IS 'Лента INSERT/UPDATE/DELETE для демонстрации работы агента с БД';
CREATE INDEX db_activity_log_ts_idx ON db_activity_log (ts DESC);
CREATE INDEX db_activity_log_run_id_idx ON db_activity_log (run_id, id DESC);

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

-- -----------------------------------------------------------------------------
-- 0a. Запуски эмуляции (ТЗ 4.6). Объявлена первой: на неё ссылаются все таблицы данных.
-- -----------------------------------------------------------------------------
CREATE TABLE sim_runs (
  id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  kind               text NOT NULL CHECK (kind IN ('baseline','free','scenario','live')), -- live: автосозданный запуск для живых контуров (ТЗ 4.7)
  label              text NOT NULL,                   -- «Baseline demo», «Сценарий 1 — Ultra», «Свободный прогон 21.10 14:05»
  scenario_id        text,                            -- FK добавляется после создания scenarios
  seed               bigint NOT NULL,
  llm_profile_id     integer,                         -- FK добавляется после создания llm_profiles
  settings_snapshot  jsonb NOT NULL DEFAULT '{}'::jsonb, -- копия settings/policies/economics на момент старта
  reset_mode         text CHECK (reset_mode IN ('none','counters','baseline')),
  parent_run_id      bigint REFERENCES sim_runs(id),  -- какой запуск был текущим перед стартом (для сравнения «до/после»)
  status             text NOT NULL DEFAULT 'running' CHECK (status IN ('running','paused','interrupted','completed','stopped','archived')),
  started_sim        timestamptz NOT NULL,
  finished_sim       timestamptz,
  started_at         timestamptz NOT NULL DEFAULT now(),
  finished_at        timestamptz,
  resumed_count      integer NOT NULL DEFAULT 0,
  summary            jsonb,                           -- итоговые метрики (ТЗ 14.1, 14.4, расход токенов) — заполняется при stop/complete
  export_path        text,                            -- runs/<id>.json после экспорта/архивации
  notes              text
);
COMMENT ON TABLE sim_runs IS 'ТЗ 4.6: история запусков эмуляции; run_id в таблицах данных ссылается сюда';
CREATE INDEX sim_runs_status_idx ON sim_runs (status, started_at DESC);

-- -----------------------------------------------------------------------------
-- 1. Справочники (ТЗ 3.x, 7, 8.2, 8.5, 14.4)
-- -----------------------------------------------------------------------------
CREATE TABLE federal_districts (
  code      text PRIMARY KEY,                      -- cfo, szfo, yufo, skfo, pfo, ufo, sfo, dfo
  name_ru   text NOT NULL,
  name_en   text NOT NULL
);

CREATE TABLE regions (
  code              text PRIMARY KEY,              -- код субъекта РФ (01..99, 77, 78, 92 …)
  name_ru           text NOT NULL,
  name_en           text NOT NULL,
  district_code     text NOT NULL REFERENCES federal_districts(code),
  population        integer NOT NULL CHECK (population > 0),
  centroid_lat      numeric(8,5) NOT NULL,
  centroid_lon      numeric(8,5) NOT NULL,
  svg_path_id       text                           -- id контура в public/map/russia.svg
);
COMMENT ON TABLE regions IS 'Все субъекты РФ; источник и лицензия — data/README.md';

CREATE TABLE cities (
  id            integer PRIMARY KEY,
  region_code   text NOT NULL REFERENCES regions(code),
  name_ru       text NOT NULL,
  name_en       text NOT NULL,
  population    integer NOT NULL CHECK (population > 0),
  lat           numeric(8,5) NOT NULL,
  lon           numeric(8,5) NOT NULL,
  is_capital    boolean NOT NULL DEFAULT false      -- административный центр субъекта
);
CREATE INDEX cities_region_idx ON cities (region_code);

CREATE TABLE segments (
  code                 text PRIMARY KEY,           -- mass, salary, social, youth, premium, vip, ultra_vip
  name_ru              text NOT NULL,
  name_en              text NOT NULL,
  population_share     numeric(5,4) NOT NULL CHECK (population_share BETWEEN 0 AND 1),
  first_response_min   integer NOT NULL,           -- SLA первого ответа клиенту, сим-минуты (ТЗ 3.1)
  priority_multiplier  numeric(3,2) NOT NULL DEFAULT 1.0,
  clv_min_rub          integer NOT NULL,
  clv_max_rub          integer NOT NULL,
  tone                 text NOT NULL,              -- ключ стиля коммуникации для промптов
  hitl_required        boolean NOT NULL DEFAULT false,
  personal_manager     boolean NOT NULL DEFAULT false
);

CREATE TABLE psychotypes (
  code      text PRIMARY KEY,                      -- loyal_pragmatic, anxious, demanding_rational, public_emotional,
                                                   -- silent_churner, bonus_hunter, novice, status_oriented
  name_ru   text NOT NULL,
  name_en   text NOT NULL,
  params    jsonb NOT NULL                         -- см. contracts/events/behavior/psychotype_params.schema.json
);
COMMENT ON TABLE psychotypes IS 'Психотипы клиентов, ТЗ 4.5; params: p_complain, complain_delay_min[2], patience_days[2], care_sensitivity, repeat_prob, channel_weights, gift_elasticity, base_churn_hazard, thank_you_prob';

CREATE TABLE segment_psychotype_mix (
  segment_code    text NOT NULL REFERENCES segments(code),
  psychotype_code text NOT NULL REFERENCES psychotypes(code),
  share           numeric(5,4) NOT NULL CHECK (share BETWEEN 0 AND 1),
  PRIMARY KEY (segment_code, psychotype_code)
);

CREATE TABLE products (
  code      text PRIMARY KEY,                      -- deposit, debit_card, credit, credit_card
  name_ru   text NOT NULL,
  name_en   text NOT NULL,
  tariffs   jsonb NOT NULL DEFAULT '{}'::jsonb,    -- ставки, комиссии
  promos    jsonb NOT NULL DEFAULT '[]'::jsonb     -- [{code, rate, valid_from_sim, valid_to_sim}]
);

CREATE TABLE systems (
  code      text PRIMARY KEY,                      -- mobile_app, web_bank, contact_center, social_listening,
                                                   -- processing, notification_gw, promo_engine, antifraud,
                                                   -- sub_deposits, sub_lending, sub_debit, core_abs
  name_ru   text NOT NULL,
  name_en   text NOT NULL,
  layer     text NOT NULL CHECK (layer IN ('front','middle','product','core'))
);

CREATE TABLE teams (
  code                  text PRIMARY KEY,          -- team_cx, team_deposits, team_lending, team_debit, team_front,
                                                   -- team_processing, team_notifications, team_contact_center,
                                                   -- team_promo, team_antifraud
  name_ru               text NOT NULL,
  name_en               text NOT NULL,
  speed_profile         jsonb NOT NULL,            -- {take_hours:[min,max], fix_days_factor, p_clarify, p_sla_breach, p_regression}
  lead_display_name     text NOT NULL              -- синтетическое имя руководителя
);

CREATE TABLE team_systems (
  team_code   text NOT NULL REFERENCES teams(code),
  system_code text NOT NULL REFERENCES systems(code),
  PRIMARY KEY (team_code, system_code)
);

CREATE TABLE channels (
  code              text PRIMARY KEY,              -- social, call, chat, email, branch, landing, telegram_bot, proactive
  name_ru           text NOT NULL,
  name_en           text NOT NULL,
  subtypes          text[] NOT NULL DEFAULT '{}',  -- vk, ok, telegram_comments, review_portal, ivr, telegram, max, whatsapp, app_chat …
  identifies_client boolean NOT NULL,
  is_public         boolean NOT NULL DEFAULT false -- соцсети: публичный ответ + перевод в личный канал
);

CREATE TABLE error_codes (
  code              text PRIMARY KEY,              -- DEP-TIMEOUT-503, PROMO-RATE-MISMATCH, PROC-DOUBLE-DEBIT, NOTIF-DELAY, APP-LOGIN-FAIL …
  system_code       text NOT NULL REFERENCES systems(code),
  product_code      text REFERENCES products(code),
  title_ru          text NOT NULL,
  default_complexity text NOT NULL CHECK (default_complexity IN ('easy','medium','hard')),
  default_criticality text NOT NULL CHECK (default_criticality IN ('low','medium','high')),
  client_visible    boolean NOT NULL DEFAULT true,
  description_ru    text
);

CREATE TABLE signal_types (
  code                text PRIMARY KEY,            -- tech_fault, client_error, tariff_terms, service_quality, fraud_suspicion,
                                                   -- legal_regulatory, info_request, gratitude, suggestion, churn
  name_ru             text NOT NULL,
  name_en             text NOT NULL,
  base_criticality    text CHECK (base_criticality IN ('low','medium','high')),
  requires_hitl       boolean NOT NULL DEFAULT false,
  creates_incident    boolean NOT NULL DEFAULT true
);

CREATE TABLE notification_templates (
  id            integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code          text NOT NULL,                     -- ack_received, proactive_fault, progress_update, resolved, gift_offer, clarify_request …
  channel_code  text NOT NULL REFERENCES channels(code),
  segment_code  text REFERENCES segments(code),    -- NULL = по умолчанию для всех сегментов
  lang          text NOT NULL DEFAULT 'ru',
  subject       text,
  body          text NOT NULL,                     -- Jinja2
  variables     text[] NOT NULL DEFAULT '{}'
);
CREATE UNIQUE INDEX notification_templates_uq ON notification_templates (code, channel_code, COALESCE(segment_code,'*'), lang);

CREATE TABLE sla_matrix (
  complexity        text NOT NULL CHECK (complexity IN ('easy','medium','hard')),
  criticality       text NOT NULL CHECK (criticality IN ('low','medium','high')),
  fix_days          smallint NOT NULL CHECK (fix_days BETWEEN 1 AND 10),
  report_days       smallint[] NOT NULL DEFAULT '{}', -- контрольные дни промежуточных отчётов, напр. {3,6,9}
  take_hours        smallint NOT NULL,                -- SLA «взято в работу», сим-часы
  PRIMARY KEY (complexity, criticality)
);
COMMENT ON TABLE sla_matrix IS 'ТЗ 8.2: easy 1/2/3, medium 3/4/5, hard 5/5(+д3)/10(+д3,6,9)';

CREATE TABLE routing_rules (
  id            integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  priority      integer NOT NULL DEFAULT 100,
  match         jsonb NOT NULL,                    -- {signal_type?, product?, system?, error_code?, flags?}
  team_codes    text[] NOT NULL,                   -- куда направлять (первый — ответственный)
  notes_ru      text
);

CREATE TABLE llm_profiles (
  id              integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code            text UNIQUE NOT NULL,            -- gigachat_ultra, gigachat_lightning, gigachat_pro, or_nemotron_ultra, or_owl_alpha, or_gpt_oss_120b, mock
  provider        text NOT NULL CHECK (provider IN ('gigachat','openai_compatible','mock')),
  model           text NOT NULL,                   -- GigaChat-3-Ultra | nvidia/nemotron-3-ultra-550b-a55b:free | …
  base_url        text,
  role            text NOT NULL CHECK (role IN ('main','fast','twin','bench_only')),
  temperature     numeric(3,2) NOT NULL DEFAULT 0,
  rpm_limit       integer,                         -- ограничитель запросов/мин (OpenRouter free: 18)
  rpd_limit       integer,                         -- запросов/сутки (OpenRouter free: 1000 при балансе ≥ $10)
  price_in_per_1m numeric(10,4) NOT NULL DEFAULT 0,
  price_out_per_1m numeric(10,4) NOT NULL DEFAULT 0,
  supports_tools  boolean NOT NULL DEFAULT true,
  supports_stream boolean NOT NULL DEFAULT true,
  is_active       boolean NOT NULL DEFAULT true,
  extra           jsonb NOT NULL DEFAULT '{}'::jsonb
);

ALTER TABLE sim_runs ADD CONSTRAINT sim_runs_llm_profile_fk FOREIGN KEY (llm_profile_id) REFERENCES llm_profiles(id);

CREATE TABLE llm_api_keys (
  id            integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  provider      text NOT NULL CHECK (provider IN ('gigachat','openai_compatible')),
  label         text NOT NULL,                     -- «физлицо», «сотрудник», «openrouter»
  encrypted_key bytea NOT NULL,                    -- pgp_sym_encrypt(key, APP_SECRET)
  tokens_used   bigint NOT NULL DEFAULT 0,
  tokens_limit  bigint,                            -- GigaChat freemium: 50 000 000 на ключ
  requests_today integer NOT NULL DEFAULT 0,
  requests_day  date,
  is_active     boolean NOT NULL DEFAULT true,
  last_error    text,
  updated_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE settings (
  key         text PRIMARY KEY,
  value       jsonb NOT NULL,
  updated_at  timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE settings IS 'Ключи: bank.name, bank.clients_profile, sim.*, policies.*, i18n.default, tgbot.enabled, twins.daily_limit, bench.* …';

CREATE TABLE dcltv_rates (
  code        text PRIMARY KEY,                    -- mobile_app, deposit, bank_average, debit_card, transfers, credit_card, payments, salary_card,
                                                   -- chat, call_center, branch, consumer_credit, premium_service, children_card, auto_loan, mortgage …
  name_ru     text NOT NULL,
  name_en     text NOT NULL,
  rate_rub    numeric(12,3) NOT NULL CHECK (rate_rub >= 0),
  maps_to     jsonb NOT NULL DEFAULT '{}'::jsonb   -- {products:[…], systems:[…], channels:[…], segments:[…]}
);
COMMENT ON TABLE dcltv_rates IS 'Ставки калькулятора «Потери от сбоев (dCLTV)»; непокрытые системы → bank_average 4050 (ТЗ 14.4)';

CREATE TABLE economics_settings (
  id                 smallint PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  detractor_share    numeric(5,4) NOT NULL DEFAULT 0.10,
  no_return_share    numeric(5,4) NOT NULL DEFAULT 0.50,
  retention_factors  jsonb NOT NULL DEFAULT '{"closed_in_sla_with_gift":1.0,"closed_in_sla":0.9,"closed_late":0.5,"closed_with_regression":0.3,"open":0,"rejected":0,"churned":0}'::jsonb,
  calibration_mode   text NOT NULL DEFAULT 'manual' CHECK (calibration_mode IN ('manual','simulated')),
  fallback_rate_code text NOT NULL DEFAULT 'bank_average' REFERENCES dcltv_rates(code) DEFERRABLE INITIALLY DEFERRED,
  updated_at         timestamptz NOT NULL DEFAULT now(),
  misselling_case_cost_rub integer NOT NULL DEFAULT 4050, -- ожидаемые потери от одного случая мисселлинга (ТЗ 14.4, уточнение 20.3 п. 1)
  map_zone_thresholds jsonb NOT NULL DEFAULT '{"yellow":0.25,"red":0.5,"copilot_weight":0.5,"window_sim_hours":24}'::jsonb -- [ДТЗ] зоны карты (ТЗ 12.2)
);

CREATE TABLE gift_catalog (
  code        text PRIMARY KEY,                    -- bonus_points, lounge_pass, restaurant_special, business_class_discount, personal_call
  name_ru     text NOT NULL,
  name_en     text NOT NULL,
  segments    text[] NOT NULL,
  rule        jsonb NOT NULL,                      -- {points_by_criticality:{low:300,medium:600,high:1000}, repeat_bonus:200, cap:1000, requires_hitl:bool, conditions:{…}}
  partner_display_name text                        -- вымышленный партнёр
);

-- -----------------------------------------------------------------------------
-- 2. Клиенты, продукты, операции
-- -----------------------------------------------------------------------------
CREATE TABLE clients (
  id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  public_id         text GENERATED ALWAYS AS ('CL-' || lpad(id::text, 6, '0')) STORED,
  display_name      text NOT NULL,                 -- синтетическое ФИО/обращение
  segment_code      text NOT NULL REFERENCES segments(code),
  psychotype_code   text NOT NULL REFERENCES psychotypes(code),
  region_code       text NOT NULL REFERENCES regions(code),
  city_id           integer NOT NULL REFERENCES cities(id),
  contacts          jsonb NOT NULL DEFAULT '{}'::jsonb, -- {phone:'+7 900 000-00-00', email:'…@example.ru', social_nick:'…'}
  telegram_chat_id  bigint,
  consents          jsonb NOT NULL DEFAULT '{"push":true,"sms":true,"email":true}'::jsonb,
  churn_risk        smallint NOT NULL DEFAULT 10 CHECK (churn_risk BETWEEN 0 AND 100),
  clv_estimate_rub  integer NOT NULL,
  activity_baseline numeric(8,2) NOT NULL DEFAULT 1, -- операций/день в норме (для детекции «молчаливого ухода»)
  social_handles    jsonb NOT NULL DEFAULT '{}'::jsonb, -- {review_portal:'@user_1234', telegram:'@tg_1234'} — синтетика, для матчинга (ТЗ 21.3)
  refunds_30d       smallint NOT NULL DEFAULT 0,     -- политика антизлоупотребления (ТЗ 9.3)
  is_active         boolean NOT NULL DEFAULT true,  -- false после account_closure
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX clients_region_idx ON clients (region_code);
CREATE INDEX clients_segment_idx ON clients (segment_code);
CREATE INDEX clients_psychotype_idx ON clients (psychotype_code);
CREATE INDEX clients_tg_idx ON clients (telegram_chat_id) WHERE telegram_chat_id IS NOT NULL;
CREATE INDEX clients_social_idx ON clients USING gin (social_handles);
CREATE TRIGGER clients_updated BEFORE UPDATE ON clients FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE client_products (
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  client_id     bigint NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  product_code  text NOT NULL REFERENCES products(code),
  status        text NOT NULL CHECK (status IN ('active','pending','closed','rejected')),
  terms         jsonb NOT NULL DEFAULT '{}'::jsonb, -- {rate, promo_code, amount, limit, masked_number:'**** 1234'}
  card_last4    char(4),                            -- последние 4 цифры невалидного по Луну номера (матчинг по «**** 4512»)
  opened_sim    timestamptz,
  closed_sim    timestamptz
);
CREATE INDEX client_products_client_idx ON client_products (client_id);
CREATE INDEX client_products_last4_idx ON client_products (card_last4) WHERE card_last4 IS NOT NULL;

CREATE TABLE operations (
  id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id            bigint NOT NULL REFERENCES sim_runs(id) ON DELETE CASCADE,
  client_id       bigint NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  product_code    text NOT NULL REFERENCES products(code),
  op_type         text NOT NULL,                   -- deposit_open, deposit_topup, transfer, card_payment, loan_payment, card_issue, limit_request, …
  system_path     text[] NOT NULL,                 -- ['mobile_app','promo_engine','sub_deposits','core_abs','notification_gw']
  amount_rub      numeric(14,2),
  method          text CHECK (method IN ('qr_sbp','card','transfer','cash','online')), -- способ (ТЗ 3.4); qr_sbp — основание RULE-QR-FEE-001
  merchant        text,                            -- вымышленный мерчант
  fee_amount      numeric(14,2) NOT NULL DEFAULT 0, -- комиссия, списанная Mock-АБС (дублирует проводку fee)
  status          text NOT NULL CHECK (status IN ('success','failed','pending','reversed')),
  error_code      text REFERENCES error_codes(code),
  fault_id        bigint,                          -- FK добавляется ниже после создания faults
  started_sim     timestamptz NOT NULL,
  finished_sim    timestamptz,
  created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX operations_client_sim_idx ON operations (client_id, started_sim DESC);
CREATE INDEX operations_error_idx ON operations (error_code) WHERE error_code IS NOT NULL;
CREATE INDEX operations_sim_idx ON operations (started_sim);
CREATE INDEX operations_run_idx ON operations (run_id);
CREATE INDEX operations_method_fee_idx ON operations (method) WHERE fee_amount > 0;

-- -----------------------------------------------------------------------------
-- 3. Системы: сбои и логи
-- -----------------------------------------------------------------------------
CREATE TABLE faults (
  id                    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id            bigint NOT NULL REFERENCES sim_runs(id) ON DELETE CASCADE,
  system_code           text NOT NULL REFERENCES systems(code),
  error_code            text NOT NULL REFERENCES error_codes(code),
  started_sim           timestamptz NOT NULL,
  resolved_sim          timestamptz,
  impact_count          integer NOT NULL DEFAULT 0,  -- затронутых операций
  affected_clients      integer NOT NULL DEFAULT 0,
  region_codes          text[] NOT NULL DEFAULT '{}', -- пусто = по всей стране
  caused_by_incident_id bigint,                      -- регрессия после фикса (FK ниже)
  created_at            timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX faults_sim_idx ON faults (started_sim DESC);
CREATE INDEX faults_run_idx ON faults (run_id);
ALTER TABLE operations ADD CONSTRAINT operations_fault_fk FOREIGN KEY (fault_id) REFERENCES faults(id);

CREATE TABLE system_logs (
  id                     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id            bigint NOT NULL REFERENCES sim_runs(id) ON DELETE CASCADE,
  system_code            text NOT NULL REFERENCES systems(code),
  level                  text NOT NULL CHECK (level IN ('INFO','WARN','ERROR','FATAL')),
  error_code             text REFERENCES error_codes(code),
  component              text NOT NULL,
  message                text NOT NULL,
  affected_operation_id  bigint REFERENCES operations(id),
  fault_id               bigint REFERENCES faults(id),
  logged_sim             timestamptz NOT NULL,
  created_at             timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX system_logs_sim_idx ON system_logs (system_code, logged_sim DESC);
CREATE INDEX system_logs_op_idx ON system_logs (affected_operation_id);

-- -----------------------------------------------------------------------------
-- 4. Сигналы и инциденты (ТЗ 6–8)
-- -----------------------------------------------------------------------------
CREATE TABLE signals (
  id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id            bigint NOT NULL REFERENCES sim_runs(id) ON DELETE CASCADE,
  public_id          text GENERATED ALWAYS AS ('SIG-' || lpad(id::text, 6, '0')) STORED,
  channel_code       text NOT NULL REFERENCES channels(code),
  channel_subtype    text,
  client_id          bigint REFERENCES clients(id),
  external_contact   jsonb,                        -- для неидентифицированных: {name, phone|email, region_code, city_id, nick, telegram_chat_id}
  text               text NOT NULL,
  lang               text NOT NULL DEFAULT 'ru',
  received_sim       timestamptz NOT NULL,
  received_at        timestamptz NOT NULL DEFAULT now(),
  status             text NOT NULL DEFAULT 'new' CHECK (status IN ('new','processing','classified','linked','deferred','awaiting_human','awaiting_client','answered','closed','noise','error')),
  origin             text NOT NULL DEFAULT 'sim' CHECK (origin IN ('sim','scenario','jury','landing','telegram_bot','proactive','twin','review_portal','voice_input','api','transcript','polling')),
  voice_meta         jsonb,                        -- голосовой ввод (ТЗ 12.2 экран 7): {stt_provider, transcript_raw, avg_confidence, duration_ms, latency_ms}
  external_post_id   bigint,                        -- пост эмулятора площадки (FK ниже, после external_posts)
  geo                jsonb,                        -- [ДТЗ] {region_code, city_id, lat, lon, source: client_profile|message|contact|ip_mock|none} (ТЗ 3.7)
  transcript_id      bigint,                        -- [ДТЗ] транскрипт-источник (FK ниже, после transcripts)
  sentiment          text CHECK (sentiment IN ('positive','neutral','negative')), -- [ДТЗ] внешняя метка FR-2.1
  source_operation_id bigint REFERENCES operations(id),
  source_fault_id    bigint REFERENCES faults(id),
  parent_signal_id   bigint REFERENCES signals(id), -- повтор/уточнение к предыдущему сигналу
  classification     jsonb,                        -- contracts/events/agent/classification.schema.json
  decision           jsonb,                        -- contracts/events/agent/decision.schema.json
  tracking_token     text UNIQUE,                  -- для /track/<token>, 24+ символов
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX signals_received_idx ON signals (received_sim DESC);
CREATE INDEX signals_run_idx ON signals (run_id, received_sim DESC);
CREATE INDEX signals_client_idx ON signals (client_id);
CREATE INDEX signals_status_idx ON signals (status);
CREATE INDEX signals_class_type_idx ON signals ((classification->>'signal_type'));
CREATE INDEX signals_geo_region_idx ON signals ((geo->>'region_code'));
CREATE INDEX signals_sentiment_idx ON signals (sentiment);
CREATE TRIGGER signals_updated BEFORE UPDATE ON signals FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER signals_activity AFTER INSERT OR UPDATE OR DELETE ON signals FOR EACH ROW EXECUTE FUNCTION log_db_activity();

CREATE TABLE incidents (
  id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id            bigint NOT NULL REFERENCES sim_runs(id) ON DELETE CASCADE,
  public_id          text GENERATED ALWAYS AS ('INC-' || lpad(id::text, 6, '0')) STORED,
  title              text NOT NULL,
  incident_type      text NOT NULL CHECK (incident_type IN ('tech_fault','client_error','tariff_terms','service_quality','fraud_suspicion','legal_regulatory','info_request','suggestion','account_closure','proactive','fee_refund','misselling')),
  product_code       text REFERENCES products(code),
  system_code        text REFERENCES systems(code),
  error_code         text REFERENCES error_codes(code),
  team_code          text NOT NULL REFERENCES teams(code),        -- ответственная команда
  co_team_codes      text[] NOT NULL DEFAULT '{}',                 -- соисполнители (например team_cx)
  complexity         text NOT NULL CHECK (complexity IN ('instant','easy','medium','hard')), -- instant: быстрый путь (ТЗ 8.1)
  criticality        text NOT NULL CHECK (criticality IN ('low','medium','high')),
  priority           smallint NOT NULL CHECK (priority BETWEEN 1 AND 4),
  status             text NOT NULL DEFAULT 'new' CHECK (status IN ('new','classified','routed','in_progress','fix_proposed','fix_deployed','verifying','resolved','closed','awaiting_human','awaiting_client','escalated','duplicate','rejected')),
  flags              text[] NOT NULL DEFAULT '{}', -- churn_intent, repeat, mass_impact, sarcasm, aggression
  mass_impact        integer NOT NULL DEFAULT 1,   -- число затронутых клиентов
  root_cause         text,
  resolution_summary text,
  region_code        text REFERENCES regions(code),
  primary_client_id  bigint REFERENCES clients(id),
  fault_id           bigint REFERENCES faults(id),
  duplicate_of_id    bigint REFERENCES incidents(id),
  created_by         text NOT NULL CHECK (created_by IN ('agent','human','team','behavior_model','scenario','compliance')),
  created_sim        timestamptz NOT NULL,
  sla_due_sim        timestamptz NOT NULL,
  take_due_sim       timestamptz NOT NULL,
  report_due_sims    timestamptz[] NOT NULL DEFAULT '{}',
  taken_sim          timestamptz,
  resolved_sim       timestamptz,
  closed_sim         timestamptz,
  sla_breached       boolean NOT NULL DEFAULT false,
  outcome_class      text CHECK (outcome_class IN ('closed_in_sla_with_gift','closed_in_sla','closed_late','closed_with_regression','open','rejected','churned')),
  agent_run_id       bigint,                       -- FK ниже
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now(),
  routing_status     text NOT NULL DEFAULT 'pending' CHECK (routing_status IN ('pending','routed','escalated','clarification','rejected')), -- [ДТЗ] лента FR-5.3
  problem_summary    jsonb                          -- [ДТЗ] {problem, severity, suggested_team} (ТЗ 7)
);
CREATE INDEX incidents_status_idx ON incidents (status);
CREATE INDEX incidents_run_idx ON incidents (run_id, status);
CREATE INDEX incidents_team_idx ON incidents (team_code, status);
CREATE INDEX incidents_sla_idx ON incidents (sla_due_sim) WHERE status NOT IN ('closed','rejected','duplicate');
CREATE INDEX incidents_dedup_idx ON incidents (error_code, system_code, created_sim) WHERE error_code IS NOT NULL;
CREATE INDEX incidents_region_idx ON incidents (region_code);
CREATE TRIGGER incidents_updated BEFORE UPDATE ON incidents FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER incidents_activity AFTER INSERT OR UPDATE OR DELETE ON incidents FOR EACH ROW EXECUTE FUNCTION log_db_activity();
ALTER TABLE faults ADD CONSTRAINT faults_caused_by_fk FOREIGN KEY (caused_by_incident_id) REFERENCES incidents(id);

CREATE TABLE incident_signals (
  incident_id  bigint NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
  signal_id    bigint NOT NULL REFERENCES signals(id) ON DELETE CASCADE,
  link_type    text NOT NULL DEFAULT 'primary' CHECK (link_type IN ('primary','linked','duplicate')),
  linked_sim   timestamptz NOT NULL,
  PRIMARY KEY (incident_id, signal_id)
);
CREATE INDEX incident_signals_signal_idx ON incident_signals (signal_id);

CREATE TABLE incident_status_history (
  id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  incident_id  bigint NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
  from_status  text,
  to_status    text NOT NULL,
  actor_type   text NOT NULL CHECK (actor_type IN ('agent','human','team','system','behavior_model')),
  actor_ref    text,                               -- team_code | user label | agent_run_id
  reason       text,
  changed_sim  timestamptz NOT NULL,
  changed_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ish_incident_idx ON incident_status_history (incident_id, changed_sim);

CREATE TABLE incident_artifacts (
  id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id            bigint NOT NULL REFERENCES sim_runs(id) ON DELETE CASCADE,
  incident_id    bigint NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
  kind           text NOT NULL CHECK (kind IN ('rca','fix_decision','progress_report','release_note','verification_report','closure_review')),
  title          text NOT NULL,
  body_md        text NOT NULL,
  meta           jsonb NOT NULL DEFAULT '{}'::jsonb, -- {report_day, version, risks[], forecast_sim}
  author_team    text REFERENCES teams(code),
  generated_by   text NOT NULL CHECK (generated_by IN ('llm','template','human')),
  due_sim        timestamptz,                        -- для progress_report: контрольный срок
  published_sim  timestamptz NOT NULL,
  created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX incident_artifacts_incident_idx ON incident_artifacts (incident_id, published_sim);

CREATE TABLE team_actions (
  id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id            bigint NOT NULL REFERENCES sim_runs(id) ON DELETE CASCADE,
  incident_id  bigint NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
  team_code    text NOT NULL REFERENCES teams(code),
  action       text NOT NULL CHECK (action IN ('take','clarify','rca','fix_decision','progress_report','release','verify','close','reassign','escalate_ack')),
  payload      jsonb NOT NULL DEFAULT '{}'::jsonb,
  action_sim   timestamptz NOT NULL,
  created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX team_actions_incident_idx ON team_actions (incident_id, action_sim);

CREATE TABLE tasks (
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id            bigint NOT NULL REFERENCES sim_runs(id) ON DELETE CASCADE,
  kind          text NOT NULL CHECK (kind IN ('gift','callback','manual_review','clarify_client','report_reminder','closure_review')),
  incident_id   bigint REFERENCES incidents(id) ON DELETE CASCADE,
  client_id     bigint REFERENCES clients(id),
  assignee      text NOT NULL DEFAULT 'cx_operator', -- cx_operator | cx_lead | team_code
  payload       jsonb NOT NULL DEFAULT '{}'::jsonb,  -- gift: {gift_code, points, privilege_code?, rationale}
  status        text NOT NULL DEFAULT 'open' CHECK (status IN ('open','approved','changed','rejected','done','cancelled')),
  requires_hitl boolean NOT NULL DEFAULT false,
  due_sim       timestamptz,
  created_sim   timestamptz NOT NULL,
  resolved_sim  timestamptz,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX tasks_status_idx ON tasks (kind, status);
CREATE INDEX tasks_run_idx ON tasks (run_id, status);
CREATE TRIGGER tasks_updated BEFORE UPDATE ON tasks FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER tasks_activity AFTER INSERT OR UPDATE ON tasks FOR EACH ROW EXECUTE FUNCTION log_db_activity();

CREATE TABLE notifications (
  id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id            bigint NOT NULL REFERENCES sim_runs(id) ON DELETE CASCADE,
  recipient_type   text NOT NULL CHECK (recipient_type IN ('client','team','public','cx')),
  client_id        bigint REFERENCES clients(id),
  team_code        text REFERENCES teams(code),
  signal_id        bigint REFERENCES signals(id),
  incident_id      bigint REFERENCES incidents(id),
  channel_code     text NOT NULL,                  -- push, sms, email, chat, social_reply, telegram_bot, tracking_page, internal
  template_code    text,
  subject          text,
  body             text NOT NULL,
  status           text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','sent','delivered','failed','suppressed','unknown')),
  sent_sim         timestamptz,
  sent_at          timestamptz,
  external_ref     text,                           -- Mailpit message id / Telegram message id
  created_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX notifications_client_idx ON notifications (client_id, created_at DESC);
CREATE INDEX notifications_run_idx ON notifications (run_id);
CREATE INDEX notifications_incident_idx ON notifications (incident_id);
CREATE INDEX notifications_signal_idx ON notifications (signal_id);
CREATE TRIGGER notifications_activity AFTER INSERT OR UPDATE ON notifications FOR EACH ROW EXECUTE FUNCTION log_db_activity();

CREATE TABLE incident_economics (
  incident_id          bigint PRIMARY KEY REFERENCES incidents(id) ON DELETE CASCADE,
  run_id               bigint NOT NULL REFERENCES sim_runs(id) ON DELETE CASCADE,
  affected_count       integer NOT NULL,
  rate_code            text NOT NULL REFERENCES dcltv_rates(code),
  rate_rub             numeric(12,3) NOT NULL,
  premium_addon_rub    numeric(12,3) NOT NULL DEFAULT 0,  -- «Премиальное обслуживание» 91,53 для premium/vip/ultra_vip
  detractor_share      numeric(5,4) NOT NULL,
  no_return_share      numeric(5,4) NOT NULL,
  potential_loss_rub   numeric(14,2) NOT NULL,
  retention_factor     numeric(5,4) NOT NULL DEFAULT 0,
  retention_source     text NOT NULL DEFAULT 'manual' CHECK (retention_source IN ('manual','simulated')),
  prevented_loss_rub   numeric(14,2) NOT NULL DEFAULT 0,
  realized_loss_rub    numeric(14,2) NOT NULL DEFAULT 0,  -- для outcome_class = churned
  breakdown            jsonb NOT NULL DEFAULT '{}'::jsonb, -- развёрнутый расчёт для карточки
  computed_sim         timestamptz NOT NULL,
  computed_at          timestamptz NOT NULL DEFAULT now(),
  refund_amount_rub numeric(14,2) NOT NULL DEFAULT 0 -- прямая стоимость возврата для fee_refund (ТЗ 14.4)
);

-- -----------------------------------------------------------------------------
-- 5. Поведение клиентов (ТЗ 4.5)
-- -----------------------------------------------------------------------------
CREATE TABLE client_states (
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id            bigint NOT NULL REFERENCES sim_runs(id) ON DELETE CASCADE,
  client_id     bigint NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  state         text NOT NULL CHECK (state IN ('calm','affected','complaining','waiting','satisfied','asks_again','escalates','churn_intent','retained','churned')),
  since_sim     timestamptz NOT NULL,
  trigger       text NOT NULL,                     -- fault | signal_sent | agent_reply | sla_breach | gift | proactive_notice | timer | closure
  incident_id   bigint REFERENCES incidents(id),
  signal_id     bigint REFERENCES signals(id),
  care_score    numeric(4,3) CHECK (care_score BETWEEN 0 AND 1),
  hazard        numeric(6,4),                      -- рассчитанная склонность к уходу на момент перехода
  is_current    boolean NOT NULL DEFAULT true,
  created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX client_states_current_idx ON client_states (client_id) WHERE is_current;
CREATE INDEX client_states_state_idx ON client_states (state) WHERE is_current;
CREATE INDEX client_states_run_idx ON client_states (run_id, incident_id);

CREATE TABLE client_reactions (
  id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id            bigint NOT NULL REFERENCES sim_runs(id) ON DELETE CASCADE,
  client_id      bigint NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  signal_id      bigint REFERENCES signals(id),
  incident_id    bigint REFERENCES incidents(id),
  notification_id bigint REFERENCES notifications(id), -- на что реагирует
  reaction       text NOT NULL CHECK (reaction IN ('satisfied','asks_again','escalates','silent','thanks','churn_intent','closes_account')),
  tone           text NOT NULL CHECK (tone IN ('neutral','positive','irritated','angry','sarcastic','formal')),
  satisfaction   numeric(4,3) CHECK (satisfaction BETWEEN 0 AND 1),
  text           text,                             -- текст двойника (может стать новым signal)
  generated_by   text NOT NULL CHECK (generated_by IN ('llm','param','mock')),
  agent_run_id   bigint,                           -- FK ниже (kind = client_twin)
  reacted_sim    timestamptz NOT NULL,
  created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX client_reactions_incident_idx ON client_reactions (incident_id);

CREATE TABLE churn_events (
  id                   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id            bigint NOT NULL REFERENCES sim_runs(id) ON DELETE CASCADE,
  client_id            bigint NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  churn_sim            timestamptz NOT NULL,
  reason               text NOT NULL,              -- unresolved_incident | sla_breach | repeated_fault | poor_communication | silent_decline | competitor
  related_incident_ids bigint[] NOT NULL DEFAULT '{}',
  offered              jsonb NOT NULL DEFAULT '{}'::jsonb, -- что предлагали: {gifts:[…], proactive:bool, first_response_min}
  days_after_incident  numeric(5,1),
  closure_incident_id  bigint REFERENCES incidents(id),  -- инцидент account_closure
  realized_loss_rub    numeric(14,2),
  created_at           timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX churn_events_sim_idx ON churn_events (churn_sim DESC);
CREATE INDEX churn_events_run_idx ON churn_events (run_id);

-- -----------------------------------------------------------------------------
-- 6. Агент: запуски, шаги, HITL, отложенные (ТЗ 9–10)
-- -----------------------------------------------------------------------------
CREATE TABLE agent_runs (
  id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  kind             text NOT NULL DEFAULT 'agent' CHECK (kind IN ('agent','client_twin','team_emulator','bench','compare','compliance_detector','speaker_attribution')),
  sim_run_id       bigint REFERENCES sim_runs(id) ON DELETE CASCADE, -- NULL для kind = bench/compare вне запуска
  signal_id        bigint REFERENCES signals(id),
  incident_id      bigint REFERENCES incidents(id),
  client_id        bigint REFERENCES clients(id),
  llm_profile_id   integer REFERENCES llm_profiles(id),
  prompt_version   text NOT NULL,
  graph_version    text NOT NULL DEFAULT '1',
  thread_id        text,                           -- LangGraph thread/checkpoint id
  started_at       timestamptz NOT NULL DEFAULT now(),
  finished_at      timestamptz,
  started_sim      timestamptz,
  outcome          text CHECK (outcome IN ('completed','awaiting_human','deferred','failed','fallback_mock','cancelled')),
  needed_human     boolean NOT NULL DEFAULT false,
  total_tokens     integer NOT NULL DEFAULT 0,
  prompt_tokens    integer NOT NULL DEFAULT 0,
  completion_tokens integer NOT NULL DEFAULT 0,
  total_latency_ms integer NOT NULL DEFAULT 0,
  cost_estimate    numeric(10,6) NOT NULL DEFAULT 0,
  error            text
);
CREATE INDEX agent_runs_started_idx ON agent_runs (started_at DESC);
CREATE INDEX agent_runs_sim_run_idx ON agent_runs (sim_run_id, started_at DESC);
CREATE INDEX agent_runs_signal_idx ON agent_runs (signal_id);
ALTER TABLE incidents ADD CONSTRAINT incidents_agent_run_fk FOREIGN KEY (agent_run_id) REFERENCES agent_runs(id);
ALTER TABLE client_reactions ADD CONSTRAINT client_reactions_run_fk FOREIGN KEY (agent_run_id) REFERENCES agent_runs(id);
CREATE TRIGGER agent_runs_activity AFTER INSERT OR UPDATE ON agent_runs FOR EACH ROW EXECUTE FUNCTION log_db_activity();

CREATE TABLE agent_steps (
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id        bigint NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
  seq           integer NOT NULL,
  node          text NOT NULL,                     -- ingest, normalize, identify_client, gather_context, check_rules, classify, decide, wait_human, act, act_instant, followup_monitor, verify, close, gift, twin_react, detect_misselling, attribute_speaker
  status        text NOT NULL CHECK (status IN ('ok','retry','fallback','error','skipped')),
  input         jsonb,
  output        jsonb,
  prompt        text,
  response_raw  text,
  reasoning     text,                              -- потоковые рассуждения модели (если модель их отдаёт)
  tool_calls    jsonb NOT NULL DEFAULT '[]'::jsonb, -- [{name, args, result, ms}]
  model         text,
  prompt_tokens integer NOT NULL DEFAULT 0,
  completion_tokens integer NOT NULL DEFAULT 0,
  latency_ms    integer NOT NULL DEFAULT 0,
  started_at    timestamptz NOT NULL DEFAULT now(),
  finished_at   timestamptz,
  UNIQUE (run_id, seq)
);
CREATE INDEX agent_steps_run_idx ON agent_steps (run_id, seq);

CREATE TABLE human_decisions (
  id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  sim_run_id       bigint NOT NULL REFERENCES sim_runs(id) ON DELETE CASCADE,
  agent_run_id     bigint REFERENCES agent_runs(id),
  signal_id        bigint REFERENCES signals(id),
  incident_id      bigint REFERENCES incidents(id),
  task_id          bigint REFERENCES tasks(id),
  requested_sim    timestamptz NOT NULL,
  requested_at     timestamptz NOT NULL DEFAULT now(),
  reason           text NOT NULL,                  -- почему потребовался человек (политика 9.3)
  agent_proposal   jsonb NOT NULL,                 -- contracts/events/agent/decision.schema.json
  options          jsonb NOT NULL,                 -- [{code,label_ru,label_en,description}]
  recommendation   text,
  decision         text CHECK (decision IN ('accept','modify','reject','delegate')),
  modified_proposal jsonb,
  decided_by       text,                           -- роль/метка пользователя (без аутентификации — из переключателя ролей)
  comment          text,
  decided_sim      timestamptz,
  decided_at       timestamptz,
  use_as_fewshot   boolean NOT NULL DEFAULT true
);
CREATE INDEX human_decisions_open_idx ON human_decisions (requested_at) WHERE decision IS NULL;
CREATE TRIGGER human_decisions_activity AFTER INSERT OR UPDATE ON human_decisions FOR EACH ROW EXECUTE FUNCTION log_db_activity();

CREATE TABLE followups (
  id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  sim_run_id  bigint NOT NULL REFERENCES sim_runs(id) ON DELETE CASCADE,
  agent_run_id bigint REFERENCES agent_runs(id),
  signal_id   bigint REFERENCES signals(id),
  incident_id bigint REFERENCES incidents(id),
  wake_sim    timestamptz NOT NULL,
  reason      text NOT NULL,                       -- awaiting_client | awaiting_team | promo_end | verify_fix | report_due | escalation_check
  payload     jsonb NOT NULL DEFAULT '{}'::jsonb,
  status      text NOT NULL DEFAULT 'scheduled' CHECK (status IN ('scheduled','fired','cancelled')),
  created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX followups_wake_idx ON followups (wake_sim) WHERE status = 'scheduled';

-- -----------------------------------------------------------------------------
-- 7. Симуляция (ТЗ 4)
-- -----------------------------------------------------------------------------
CREATE TABLE sim_state (
  id              smallint PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  sim_time        timestamptz NOT NULL,
  day_no          integer NOT NULL DEFAULT 1,
  speed           numeric(8,2) NOT NULL DEFAULT 60, -- сим-секунд на реальную секунду (60 = сим-час за минуту)
  running         boolean NOT NULL DEFAULT false,
  seed            bigint NOT NULL,
  phase           text NOT NULL DEFAULT 'morning', -- morning | day | evening | night (для циркадной темы)
  current_run_id  bigint REFERENCES sim_runs(id),  -- текущий запуск (ТЗ 4.6)
  rng_state       jsonb,                           -- сериализованное состояние генератора для возобновления
  last_tick_at    timestamptz,                     -- для определения прерывания при старте приложения
  intensities     jsonb NOT NULL DEFAULT '{}'::jsonb, -- переопределения интенсивностей 4.2
  updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE sim_events (
  id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id      bigint NOT NULL REFERENCES sim_runs(id) ON DELETE CASCADE,
  event_type  text NOT NULL,                       -- см. contracts/events/sim/*.schema.json: op.*, fault.*, client_error.*, signal.*, team.*, sla.*, client.*
  payload     jsonb NOT NULL,
  sim_time    timestamptz NOT NULL,
  real_time   timestamptz NOT NULL DEFAULT now(),
  scenario_id text,                                -- если порождено сценарием
  correlation_id uuid NOT NULL DEFAULT gen_random_uuid()
);
CREATE INDEX sim_events_sim_idx ON sim_events (sim_time DESC);
CREATE INDEX sim_events_run_idx ON sim_events (run_id, sim_time DESC);
CREATE INDEX sim_events_type_idx ON sim_events (event_type, sim_time DESC);

CREATE TABLE scenarios (
  id            text PRIMARY KEY,                  -- deposit_promo_rate, double_fee, jury_input, potential_client, deferred_fraud, mass_notif, silent_churn_regression
  title_ru      text NOT NULL,
  title_en      text NOT NULL,
  yaml_source   text NOT NULL,
  expected      jsonb NOT NULL DEFAULT '{}'::jsonb,
  last_run_at   timestamptz,
  last_result   jsonb
);
ALTER TABLE sim_runs ADD CONSTRAINT sim_runs_scenario_fk FOREIGN KEY (scenario_id) REFERENCES scenarios(id);

-- -----------------------------------------------------------------------------
-- 8. Бенчмарки (ТЗ 14)
-- -----------------------------------------------------------------------------
CREATE TABLE bench_datasets (
  id          integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code        text UNIQUE NOT NULL,                -- golden_v1, lite_v1
  title_ru    text NOT NULL,
  description text,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE bench_cases (
  id            integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  dataset_id    integer NOT NULL REFERENCES bench_datasets(id) ON DELETE CASCADE,
  channel_code  text NOT NULL REFERENCES channels(code),
  segment_code  text REFERENCES segments(code),
  text          text NOT NULL,
  gold          jsonb NOT NULL,                    -- {signal_type, product, system, criticality, complexity, team, flags[], needs_hitl}
  tags          text[] NOT NULL DEFAULT '{}'
);
CREATE INDEX bench_cases_dataset_idx ON bench_cases (dataset_id);

CREATE TABLE bench_runs (
  id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  dataset_id      integer NOT NULL REFERENCES bench_datasets(id),
  llm_profile_id  integer NOT NULL REFERENCES llm_profiles(id),
  prompt_version  text NOT NULL,
  seed            bigint,
  repeats         smallint NOT NULL DEFAULT 1,
  status          text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','running','done','failed','cancelled')),
  metrics         jsonb,                           -- {accuracy_type, accuracy_route, f1_critical, json_valid_rate, tool_success_rate, p50_ms, p95_ms, tokens_total, cost, stability}
  started_at      timestamptz,
  finished_at     timestamptz,
  error           text
);

CREATE TABLE bench_results (
  id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id      bigint NOT NULL REFERENCES bench_runs(id) ON DELETE CASCADE,
  case_id     integer NOT NULL REFERENCES bench_cases(id),
  repeat_no   smallint NOT NULL DEFAULT 1,
  predicted   jsonb NOT NULL,
  correct     jsonb NOT NULL,                      -- {signal_type:bool, product:bool, system:bool, criticality:bool, team:bool}
  json_valid_first_try boolean NOT NULL,
  retries     smallint NOT NULL DEFAULT 0,
  latency_ms  integer NOT NULL,
  prompt_tokens integer NOT NULL DEFAULT 0,
  completion_tokens integer NOT NULL DEFAULT 0,
  fallback_mock boolean NOT NULL DEFAULT false,
  UNIQUE (run_id, case_id, repeat_no)
);

-- -----------------------------------------------------------------------------
-- 9. Представления для дашборда и калькулятора «Факт по симуляции» (ТЗ 14.5)
-- -----------------------------------------------------------------------------
CREATE VIEW v_faults_by_product_hour AS
SELECT f.run_id,
       ec.product_code,
       f.system_code,
       date_trunc('day', f.started_sim)  AS sim_day,
       extract(hour FROM f.started_sim)::int AS sim_hour,
       count(*)                           AS faults,
       sum(f.impact_count)                AS operations_affected,
       sum(f.affected_clients)            AS clients_affected
FROM faults f JOIN error_codes ec ON ec.code = f.error_code
GROUP BY 1,2,3,4,5;

CREATE VIEW v_incident_outcomes AS
SELECT i.run_id,
       i.outcome_class,
       i.product_code,
       i.team_code,
       count(*)                                   AS incidents,
       coalesce(sum(e.potential_loss_rub),0)      AS potential_loss_rub,
       coalesce(sum(e.prevented_loss_rub),0)      AS prevented_loss_rub,
       coalesce(sum(e.realized_loss_rub),0)       AS realized_loss_rub
FROM incidents i LEFT JOIN incident_economics e ON e.incident_id = i.id
GROUP BY 1,2,3,4;

CREATE VIEW v_retention_by_outcome AS
-- фактическая доля удержанных среди затронутых по классам исхода — источник для calibration_mode = simulated
SELECT i.run_id,
       i.outcome_class,
       count(DISTINCT cs.client_id) FILTER (WHERE cs.state = 'retained') AS retained,
       count(DISTINCT cs.client_id) FILTER (WHERE cs.state IN ('retained','churned')) AS resolved_clients,
       CASE WHEN count(DISTINCT cs.client_id) FILTER (WHERE cs.state IN ('retained','churned')) = 0 THEN NULL
            ELSE round(count(DISTINCT cs.client_id) FILTER (WHERE cs.state = 'retained')::numeric
                       / count(DISTINCT cs.client_id) FILTER (WHERE cs.state IN ('retained','churned')), 4) END AS retention_rate
FROM incidents i JOIN client_states cs ON cs.incident_id = i.id
GROUP BY 1,2;

CREATE VIEW v_region_heat AS
-- тепловая карта текущего запуска (плюс baseline-данные не включаются: окно 24 ч и текущий run)
SELECT s.region_code,
       count(*) FILTER (WHERE s.received_sim > (SELECT sim_time - interval '24 hours' FROM sim_state)) AS signals_24h,
       count(*) FILTER (WHERE (s.classification->>'criticality') = 'high'
                        AND s.received_sim > (SELECT sim_time - interval '24 hours' FROM sim_state)) AS critical_24h
FROM (SELECT sg.run_id, sg.received_sim, sg.classification, coalesce(c.region_code, sg.external_contact->>'region_code') AS region_code
      FROM signals sg LEFT JOIN clients c ON c.id = sg.client_id) s
WHERE s.region_code IS NOT NULL
  AND s.run_id = (SELECT current_run_id FROM sim_state)
GROUP BY 1;

CREATE VIEW v_run_counters AS
-- живые счётчики текущего/любого запуска для панели «Запуски» (итоговый summary считается приложением при stop)
SELECT r.id AS run_id, r.kind, r.label, r.status, r.started_sim, r.finished_sim,
       (SELECT count(*) FROM signals s WHERE s.run_id = r.id)                                   AS signals,
       (SELECT count(*) FROM incidents i WHERE i.run_id = r.id)                                 AS incidents,
       (SELECT count(*) FROM incidents i WHERE i.run_id = r.id AND i.status NOT IN ('closed','rejected','duplicate')) AS incidents_open,
       (SELECT count(*) FROM incidents i WHERE i.run_id = r.id AND i.sla_breached)              AS sla_breached,
       (SELECT count(*) FROM human_decisions h WHERE h.sim_run_id = r.id)                       AS hitl_requests,
       (SELECT count(*) FROM churn_events c WHERE c.run_id = r.id)                              AS churned,
       (SELECT coalesce(sum(total_tokens),0) FROM agent_runs a WHERE a.sim_run_id = r.id)       AS tokens,
       (SELECT coalesce(sum(prevented_loss_rub),0) FROM incident_economics e WHERE e.run_id = r.id) AS prevented_loss_rub,
       (SELECT coalesce(sum(realized_loss_rub),0) FROM incident_economics e WHERE e.run_id = r.id)  AS realized_loss_rub
FROM sim_runs r;

-- -----------------------------------------------------------------------------
-- v1.3: контуры BRD демо-стенда (разделы 11–16)
-- -----------------------------------------------------------------------------
-- 11. Mock-АБС: счета, тарифы, проводки (ТЗ 3.4, 21.4)
-- -----------------------------------------------------------------------------
CREATE TABLE accounts (
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
CREATE INDEX accounts_client_idx ON accounts (client_id);
CREATE TRIGGER accounts_updated BEFORE UPDATE ON accounts FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE tariffs (
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

CREATE TABLE ledger_entries (
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
CREATE INDEX ledger_account_idx ON ledger_entries (account_id, posted_sim DESC);
CREATE INDEX ledger_operation_idx ON ledger_entries (operation_id);
CREATE INDEX ledger_run_idx ON ledger_entries (run_id);
CREATE TRIGGER ledger_entries_activity AFTER INSERT ON ledger_entries FOR EACH ROW EXECUTE FUNCTION log_db_activity();

-- -----------------------------------------------------------------------------
-- 12. Детерминированные бизнес-правила (ТЗ 9.6)
-- -----------------------------------------------------------------------------
CREATE TABLE business_rules (
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
CREATE TRIGGER business_rules_updated BEFORE UPDATE ON business_rules FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE rule_evaluations (
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
CREATE INDEX rule_evaluations_signal_idx ON rule_evaluations (signal_id);
CREATE INDEX rule_evaluations_run_idx ON rule_evaluations (run_id);

-- -----------------------------------------------------------------------------
-- 13. Внешние площадки: посты и публичные ответы (ТЗ 21.2, 21.5)
-- -----------------------------------------------------------------------------
CREATE TABLE external_posts (
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
CREATE INDEX external_posts_run_idx ON external_posts (run_id, posted_at DESC);
CREATE INDEX external_posts_status_idx ON external_posts (status);
CREATE TRIGGER external_posts_updated BEFORE UPDATE ON external_posts FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER external_posts_activity AFTER INSERT OR UPDATE ON external_posts FOR EACH ROW EXECUTE FUNCTION log_db_activity();
ALTER TABLE signals ADD CONSTRAINT signals_external_post_fk FOREIGN KEY (external_post_id) REFERENCES external_posts(id);

CREATE TABLE external_replies (
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
CREATE INDEX external_replies_post_idx ON external_replies (post_id, published_at);

-- -----------------------------------------------------------------------------
-- 14. Отделения, сотрудники, аудиосессии, мисселлинг (ТЗ 22)
-- -----------------------------------------------------------------------------
CREATE TABLE branches (
  id          integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code        text NOT NULL UNIQUE,                   -- 'VSP-0042'
  name_ru     text NOT NULL,
  city_id     integer NOT NULL REFERENCES cities(id),
  region_code text NOT NULL REFERENCES regions(code),
  desks       smallint NOT NULL DEFAULT 6,
  manager_display_name text NOT NULL,                 -- руководитель отделения (синтетическое ФИО)
  manager_chat_id bigint                              -- Telegram руководителя для алертов (опционально)
);

CREATE TABLE employees (
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
CREATE INDEX employees_branch_idx ON employees (branch_id);

CREATE TABLE misselling_patterns (
  code         text PRIMARY KEY,                      -- tie_in, substitution, concealment, pressure, guarantee
  name_ru      text NOT NULL,
  name_en      text NOT NULL,
  description_ru text NOT NULL,
  examples     text[] NOT NULL DEFAULT '{}',
  counter_examples text[] NOT NULL DEFAULT '{}',      -- что НЕ является нарушением
  keywords     text[] NOT NULL DEFAULT '{}',          -- для rule-детектора
  weight       numeric(4,2) NOT NULL DEFAULT 1,
  is_active    boolean NOT NULL DEFAULT true,
  family       text NOT NULL DEFAULT 'misselling' CHECK (family IN ('misselling','conduct')), -- [ДТЗ]
  alert_policy text NOT NULL DEFAULT 'counter' CHECK (alert_policy IN ('counter','immediate','report')), -- [ДТЗ]
  immediate_threshold numeric(4,3) NOT NULL DEFAULT 0.8,
  recommendation_ru text,                            -- [ДТЗ] шаблон рекомендации руководителю (ТЗ 22.9)
  training_module text                               -- [ДТЗ] код учебного модуля
);
COMMENT ON TABLE misselling_patterns IS 'Таксономия нарушений сотрудника: семейства misselling (ТЗ 22.4) и conduct — rudeness, script_violation, misinformation (ТЗ 22.8); имя таблицы сохранено для совместимости v1.3';

CREATE TABLE audio_sessions (
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
  pacing           text NOT NULL DEFAULT 'realtime' CHECK (pacing IN ('realtime','batch')), -- [ДТЗ] batch = готовый транскрипт целиком (ТЗ 22.8)
  transcript_id    bigint,                            -- [ДТЗ] FK ниже (transcripts)
  report           jsonb,                             -- [ДТЗ] transcript_report для pacing = batch
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX audio_sessions_run_idx ON audio_sessions (run_id, started_at DESC);
CREATE INDEX audio_sessions_employee_idx ON audio_sessions (employee_id);
CREATE TRIGGER audio_sessions_updated BEFORE UPDATE ON audio_sessions FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER audio_sessions_activity AFTER INSERT OR UPDATE ON audio_sessions FOR EACH ROW EXECUTE FUNCTION log_db_activity();

CREATE TABLE utterances (
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
CREATE INDEX utterances_session_idx ON utterances (session_id, seq);

CREATE TABLE compliance_triggers (
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
  recommendation_ru text,                             -- [ДТЗ] рекомендация по отработке (ТЗ 22.9)
  fact_check    jsonb,                                -- [ДТЗ] {claim, truth, source_table, source_key, verified} для misinformation
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now(),
  UNIQUE (utterance_id)                               -- не более одного триггера на реплику (ТЗ 22.4)
);
CREATE INDEX compliance_triggers_session_idx ON compliance_triggers (session_id);
CREATE TRIGGER compliance_triggers_updated BEFORE UPDATE ON compliance_triggers FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER compliance_triggers_activity AFTER INSERT OR UPDATE ON compliance_triggers FOR EACH ROW EXECUTE FUNCTION log_db_activity();

CREATE TABLE compliance_alerts (
  id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  session_id       bigint NOT NULL REFERENCES audio_sessions(id) ON DELETE CASCADE,
  incident_id      bigint REFERENCES incidents(id),
  sent_at          timestamptz NOT NULL DEFAULT now(),
  channels         text[] NOT NULL DEFAULT '{ws}',    -- ws, telegram
  latency_ms       integer,                           -- порог → отправка
  acknowledged_at  timestamptz,
  acknowledged_by  text,                              -- роль/имя (синтетическое)
  decision         text CHECK (decision IN ('go','false_positive','open_incident','acknowledged')),
  human_decision_id bigint REFERENCES human_decisions(id),
  recommendation_ru text,                            -- [ДТЗ]
  kind             text NOT NULL DEFAULT 'threshold' CHECK (kind IN ('threshold','immediate','report')), -- [ДТЗ] политика алерта
  transcript_id    bigint                            -- [ДТЗ] FK ниже (transcripts)
);
CREATE INDEX compliance_alerts_session_idx ON compliance_alerts (session_id);

CREATE TABLE stt_metrics (
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
-- 15. Режим подстраховки: кассеты LLM и демо-активы (ТЗ 5.4, 12.7)
-- -----------------------------------------------------------------------------
CREATE TABLE llm_cassettes (
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

CREATE TABLE demo_assets (
  id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  kind         text NOT NULL CHECK (kind IN ('audio','transcript','post','cassette')),
  scenario_id  text,
  title_ru     text NOT NULL,
  path         text NOT NULL,                         -- data/audio/scenario9_01.wav
  checksum     text NOT NULL,
  ref          jsonb,                                 -- эталонный транскрипт с ролями/таймкодами или текст поста
  duration_ms  integer
);
ALTER TABLE audio_sessions ADD CONSTRAINT audio_sessions_demo_asset_fk FOREIGN KEY (demo_asset_id) REFERENCES demo_assets(id);

-- -----------------------------------------------------------------------------
-- 16. Представления для живых контуров (ТЗ 14.1)
-- -----------------------------------------------------------------------------
CREATE VIEW v_feed_latency AS
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

CREATE VIEW v_compliance_by_employee AS
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

-- -----------------------------------------------------------------------------
-- v1.4: дополнительное ТЗ (разделы 17–19)
-- -----------------------------------------------------------------------------
-- 17. Приёмный слой ingest (ТЗ 3.7)
-- -----------------------------------------------------------------------------
CREATE TABLE ingest_sources (
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
CREATE TRIGGER ingest_sources_updated BEFORE UPDATE ON ingest_sources FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE transcripts (
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
CREATE INDEX transcripts_run_idx ON transcripts (run_id, received_at DESC);
CREATE INDEX transcripts_status_idx ON transcripts (status);
CREATE INDEX transcripts_employee_idx ON transcripts (employee_id);
CREATE TRIGGER transcripts_updated BEFORE UPDATE ON transcripts FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER transcripts_activity AFTER INSERT OR UPDATE ON transcripts FOR EACH ROW EXECUTE FUNCTION log_db_activity();

ALTER TABLE signals ADD CONSTRAINT signals_transcript_fk FOREIGN KEY (transcript_id) REFERENCES transcripts(id);
ALTER TABLE audio_sessions ADD CONSTRAINT audio_sessions_transcript_fk FOREIGN KEY (transcript_id) REFERENCES transcripts(id);
ALTER TABLE compliance_alerts ADD CONSTRAINT compliance_alerts_transcript_fk FOREIGN KEY (transcript_id) REFERENCES transcripts(id);

CREATE TABLE ingest_messages (
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
CREATE INDEX ingest_messages_run_idx ON ingest_messages (run_id, received_at DESC);

-- -----------------------------------------------------------------------------
-- 18. Эскалации и тикетница (ТЗ 9.7)
-- -----------------------------------------------------------------------------
CREATE TABLE escalations (
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
CREATE INDEX escalations_run_idx ON escalations (run_id, created_at DESC);
CREATE INDEX escalations_status_idx ON escalations (status);
CREATE TRIGGER escalations_updated BEFORE UPDATE ON escalations FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER escalations_activity AFTER INSERT OR UPDATE ON escalations FOR EACH ROW EXECUTE FUNCTION log_db_activity();

CREATE TABLE service_scripts (
  code        text PRIMARY KEY,                        -- retail_service_v1
  kind        text NOT NULL CHECK (kind IN ('retail_service','retail_sales','contact_center')),
  name_ru     text NOT NULL,
  steps       jsonb NOT NULL,                          -- [{code, name_ru, required, markers[], forbidden_phrases[]}]
  version     integer NOT NULL DEFAULT 1,
  is_active   boolean NOT NULL DEFAULT true,
  updated_at  timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE service_scripts IS 'Эталонные скрипты обслуживания для проверки script_violation (ТЗ 22.8)';
CREATE TRIGGER service_scripts_updated BEFORE UPDATE ON service_scripts FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- -----------------------------------------------------------------------------
-- 19. Представления: тикетница и зоны карты (ТЗ 9.7, 12.2)
-- -----------------------------------------------------------------------------
CREATE VIEW v_tickets AS
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

CREATE VIEW v_map_zones AS
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

-- -----------------------------------------------------------------------------
-- 10. Канал событий для backend (LISTEN/NOTIFY)
-- -----------------------------------------------------------------------------
-- Каналы: 'sim_events' (новые события симулятора), 'db_activity' (триггеры), 'agent_stream' (шаги/токены),
-- 'incidents' (смены статусов), 'notifications', 'sim_runs' (старт/стоп/возобновление запуска),
-- v1.3: 'feed', 'abs', 'compliance', 'stt', 'demo' (см. комментарий в конце раздела 16);
-- v1.4: 'ingest', 'escalations', 'tickets', 'zones' (см. комментарий в конце раздела 19).
-- Снимок baseline (ТЗ 4.6): pg_dump -Fc всех таблиц, КРОМЕ sim_runs с kind<>'baseline' и их данных; таблица sim_runs и
-- каталог runs/ сохраняются приложением отдельно и возвращаются после pg_restore. Публикация — из приложения через pg_notify, кроме db_activity.

-- =============================================================================
-- 20. След и поиск v1.5 (миграция 0004, идемпотентно на свежей схеме)
-- =============================================================================
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- -----------------------------------------------------------------------------
-- A. Генерируемые public_id (ТЗ 28.2, 20.7 № 62)
-- -----------------------------------------------------------------------------
ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS public_id text GENERATED ALWAYS AS ('AR-' || lpad(id::text, 6, '0')) STORED;
ALTER TABLE sim_runs ADD COLUMN IF NOT EXISTS public_id text GENERATED ALWAYS AS ('SR-' || lpad(id::text, 4, '0')) STORED;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS public_id text GENERATED ALWAYS AS ('TSK-' || lpad(id::text, 6, '0')) STORED;
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS public_id text GENERATED ALWAYS AS ('NTF-' || lpad(id::text, 6, '0')) STORED;
ALTER TABLE ledger_entries ADD COLUMN IF NOT EXISTS public_id text GENERATED ALWAYS AS ('LED-' || lpad(id::text, 6, '0')) STORED;
ALTER TABLE human_decisions ADD COLUMN IF NOT EXISTS public_id text GENERATED ALWAYS AS ('HD-' || lpad(id::text, 6, '0')) STORED;
ALTER TABLE followups ADD COLUMN IF NOT EXISTS public_id text GENERATED ALWAYS AS ('FUP-' || lpad(id::text, 6, '0')) STORED;

CREATE UNIQUE INDEX IF NOT EXISTS agent_runs_public_id_uidx ON agent_runs (public_id);
CREATE UNIQUE INDEX IF NOT EXISTS sim_runs_public_id_uidx ON sim_runs (public_id);
CREATE UNIQUE INDEX IF NOT EXISTS tasks_public_id_uidx ON tasks (public_id);
CREATE UNIQUE INDEX IF NOT EXISTS notifications_public_id_uidx ON notifications (public_id);
CREATE UNIQUE INDEX IF NOT EXISTS ledger_entries_public_id_uidx ON ledger_entries (public_id);
CREATE UNIQUE INDEX IF NOT EXISTS human_decisions_public_id_uidx ON human_decisions (public_id);
CREATE UNIQUE INDEX IF NOT EXISTS followups_public_id_uidx ON followups (public_id);

-- -----------------------------------------------------------------------------
-- B. Полнотекстовый и триграммный поиск (ТЗ 28.2)
-- -----------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS signals_text_fts_idx ON signals USING gin (to_tsvector('russian', text));
CREATE INDEX IF NOT EXISTS incidents_title_fts_idx ON incidents USING gin (to_tsvector('russian', title));
CREATE INDEX IF NOT EXISTS external_posts_text_fts_idx ON external_posts USING gin (to_tsvector('russian', text));

CREATE INDEX IF NOT EXISTS agent_runs_public_id_trgm_idx ON agent_runs USING gin (public_id gin_trgm_ops);
CREATE INDEX IF NOT EXISTS sim_runs_public_id_trgm_idx ON sim_runs USING gin (public_id gin_trgm_ops);
CREATE INDEX IF NOT EXISTS tasks_public_id_trgm_idx ON tasks USING gin (public_id gin_trgm_ops);
CREATE INDEX IF NOT EXISTS notifications_public_id_trgm_idx ON notifications USING gin (public_id gin_trgm_ops);
CREATE INDEX IF NOT EXISTS ledger_entries_public_id_trgm_idx ON ledger_entries USING gin (public_id gin_trgm_ops);
CREATE INDEX IF NOT EXISTS human_decisions_public_id_trgm_idx ON human_decisions USING gin (public_id gin_trgm_ops);
CREATE INDEX IF NOT EXISTS followups_public_id_trgm_idx ON followups USING gin (public_id gin_trgm_ops);
CREATE INDEX IF NOT EXISTS clients_social_handles_trgm_idx ON clients USING gin ((social_handles::text) gin_trgm_ops);

-- -----------------------------------------------------------------------------
-- C. Индексы по FK цепочки следа (ТЗ 28.7)
-- -----------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS incident_signals_incident_idx ON incident_signals (incident_id);
CREATE INDEX IF NOT EXISTS tasks_incident_idx ON tasks (incident_id) WHERE incident_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS external_replies_incident_idx ON external_replies (incident_id) WHERE incident_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS external_replies_agent_run_idx ON external_replies (agent_run_id) WHERE agent_run_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS client_reactions_notification_idx ON client_reactions (notification_id) WHERE notification_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS client_reactions_agent_run_idx ON client_reactions (agent_run_id) WHERE agent_run_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS followups_incident_idx ON followups (incident_id) WHERE incident_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS followups_signal_idx ON followups (signal_id) WHERE signal_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS followups_agent_run_idx ON followups (agent_run_id) WHERE agent_run_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS human_decisions_incident_idx ON human_decisions (incident_id) WHERE incident_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS human_decisions_signal_idx ON human_decisions (signal_id) WHERE signal_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS human_decisions_agent_run_idx ON human_decisions (agent_run_id) WHERE agent_run_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS escalations_incident_idx ON escalations (incident_id) WHERE incident_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS escalations_signal_idx ON escalations (signal_id) WHERE signal_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS escalations_agent_run_idx ON escalations (agent_run_id) WHERE agent_run_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ledger_entries_agent_run_idx ON ledger_entries (agent_run_id) WHERE agent_run_id IS NOT NULL;

-- =============================================================================
-- 21. Кабинет, CSI и ВСП v1.5 (миграция 0005, идемпотентно на свежей схеме)
-- =============================================================================
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

-- T-265: доказательства финансового эффекта, миграция 0008.
-- T-265: неизменяемые версии доказательств; сумма и основания берутся из согласованной политики.
CREATE TABLE IF NOT EXISTS financial_evidence (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id bigint NOT NULL REFERENCES sim_runs(id) ON DELETE CASCADE,
  incident_id bigint NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
  alert_id bigint NOT NULL REFERENCES compliance_alerts(id),
  scope text NOT NULL CHECK (scope IN ('demo','observed')),
  deal_ref text NOT NULL CHECK (length(deal_ref) BETWEEN 1 AND 120),
  idempotency_key text NOT NULL CHECK (length(idempotency_key) BETWEEN 1 AND 120),
  payload_sha256 text NOT NULL CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
  intervention_sim timestamptz NOT NULL,
  deal_closed_sim timestamptz NOT NULL,
  outcome text NOT NULL CHECK (outcome IN ('prevented','completed','unknown')),
  evidence_ref text NOT NULL CHECK (length(evidence_ref) BETWEEN 1 AND 500),
  recorded_by text NOT NULL CHECK (length(recorded_by) BETWEEN 1 AND 120),
  policy jsonb NOT NULL,
  policy_sha256 text NOT NULL CHECK (policy_sha256 ~ '^[0-9a-f]{64}$'),
  recorded_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (run_id, scope, idempotency_key)
);
CREATE INDEX IF NOT EXISTS financial_evidence_deal_idx ON financial_evidence (run_id, scope, deal_ref, id DESC);
CREATE INDEX IF NOT EXISTS financial_evidence_incident_idx ON financial_evidence (incident_id, scope, id DESC);
CREATE OR REPLACE FUNCTION reject_financial_evidence_update() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'financial_evidence is append-only; add a new version';
END $$;
DROP TRIGGER IF EXISTS financial_evidence_immutable ON financial_evidence;
CREATE TRIGGER financial_evidence_immutable BEFORE UPDATE ON financial_evidence
FOR EACH ROW EXECUTE FUNCTION reject_financial_evidence_update();
DROP TRIGGER IF EXISTS financial_evidence_activity ON financial_evidence;
CREATE TRIGGER financial_evidence_activity AFTER INSERT ON financial_evidence
FOR EACH ROW EXECUTE FUNCTION log_db_activity();

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

-- T-108: полная наблюдаемость изменений без записи содержимого строк в аудит.
CREATE TRIGGER incident_signals_activity AFTER INSERT OR UPDATE OR DELETE ON incident_signals FOR EACH ROW EXECUTE FUNCTION log_db_activity();
CREATE TRIGGER incident_status_history_activity AFTER INSERT OR UPDATE OR DELETE ON incident_status_history FOR EACH ROW EXECUTE FUNCTION log_db_activity();
CREATE TRIGGER agent_steps_activity AFTER INSERT OR UPDATE OR DELETE ON agent_steps FOR EACH ROW EXECUTE FUNCTION log_db_activity();
CREATE TRIGGER client_states_activity AFTER INSERT OR UPDATE OR DELETE ON client_states FOR EACH ROW EXECUTE FUNCTION log_db_activity();
CREATE TRIGGER churn_events_activity AFTER INSERT OR UPDATE OR DELETE ON churn_events FOR EACH ROW EXECUTE FUNCTION log_db_activity();
CREATE TRIGGER incident_economics_activity AFTER INSERT OR UPDATE OR DELETE ON incident_economics FOR EACH ROW EXECUTE FUNCTION log_db_activity();
CREATE TRIGGER faults_activity AFTER INSERT OR UPDATE OR DELETE ON faults FOR EACH ROW EXECUTE FUNCTION log_db_activity();

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

-- T-051: единый реестр credential configuration и snapshot на AgentRun.
-- Operational ledger/UTC quotas сюда не входят (T-050, отдельная миграция).
ALTER TABLE llm_api_keys DROP CONSTRAINT IF EXISTS llm_api_keys_provider_check;
ALTER TABLE llm_api_keys ADD CONSTRAINT llm_api_keys_provider_check CHECK(provider IN ('gigachat','openai_compatible','mock'));
ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS llm_profiles_snapshot jsonb;
ALTER TABLE llm_api_keys ADD COLUMN IF NOT EXISTS credential_uid uuid NOT NULL DEFAULT gen_random_uuid();
ALTER TABLE llm_api_keys ADD COLUMN IF NOT EXISTS endpoint_url text;
ALTER TABLE llm_api_keys ADD COLUMN IF NOT EXISTS scope text;
ALTER TABLE llm_api_keys ADD COLUMN IF NOT EXISTS key_hint text;
ALTER TABLE llm_api_keys ADD COLUMN IF NOT EXISTS rpd_limit integer;
ALTER TABLE llm_api_keys ADD COLUMN IF NOT EXISTS balance_usd numeric;
ALTER TABLE llm_api_keys ADD COLUMN IF NOT EXISTS created_at timestamptz NOT NULL DEFAULT now();
ALTER TABLE llm_api_keys ADD COLUMN IF NOT EXISTS deleted_at timestamptz;
ALTER TABLE llm_profiles ADD COLUMN IF NOT EXISTS api_key_id integer;
DO $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conname='llm_profiles_api_key_fk') THEN
  ALTER TABLE llm_profiles ADD CONSTRAINT llm_profiles_api_key_fk FOREIGN KEY(api_key_id) REFERENCES llm_api_keys(id) ON DELETE RESTRICT;
 END IF;
END $$;
COMMENT ON COLUMN agent_runs.llm_profiles_snapshot IS 'T-051: versioned secret-free role configuration before first LLM; NULL is legacy, not invented history';
COMMENT ON COLUMN llm_api_keys.credential_uid IS 'Private logical identity, never projected by API; no operational counters in model snapshots';
COMMENT ON COLUMN llm_profiles.api_key_id IS 'Explicit credential binding; invalid/revoked/mismatched key never falls back to env';

-- Fail-closed rollback: прежнее приложение не может завести второй writable store.
-- Существующая encrypted legacy row читается конвертером и удаляется только при commit.
CREATE OR REPLACE FUNCTION reject_legacy_llm_key_writes() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.key='llm_keys' THEN
  RAISE EXCEPTION 'Legacy LLM key writes are disabled; use canonical credential registry' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS settings_legacy_llm_key_writes ON settings;
CREATE TRIGGER settings_legacy_llm_key_writes BEFORE INSERT OR UPDATE ON settings
 FOR EACH ROW EXECUTE FUNCTION reject_legacy_llm_key_writes();
-- T-240: история принадлежит запуску; неизвестное происхождение legacy не угадываем.
ALTER TABLE product_signal_history
  ADD COLUMN IF NOT EXISTS run_id bigint REFERENCES sim_runs(id) ON DELETE CASCADE,
  ADD COLUMN IF NOT EXISTS sentiment_known_count integer,
  ADD COLUMN IF NOT EXISTS is_partial boolean,
  ADD COLUMN IF NOT EXISTS coverage_start timestamptz,
  ADD COLUMN IF NOT EXISTS coverage_end timestamptz;
ALTER TABLE product_signal_history ALTER COLUMN loss_rub DROP NOT NULL;
ALTER TABLE product_signal_history ALTER COLUMN loss_rub DROP DEFAULT;

-- Имя старого UNIQUE могло отличаться у оператора: сопоставляем реальные колонки.
DO $$
DECLARE old_key record;
BEGIN
  FOR old_key IN
    SELECT c.conname FROM pg_constraint c
    WHERE c.conrelid = 'product_signal_history'::regclass AND c.contype = 'u'
      AND (SELECT array_agg(a.attname::text ORDER BY a.attname)
           FROM unnest(c.conkey) k(attnum)
           JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=k.attnum)
          = ARRAY['month','product_line_code']::text[]
  LOOP
    EXECUTE 'ALTER TABLE product_signal_history DROP CONSTRAINT ' || quote_ident(old_key.conname);
  END LOOP;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                 WHERE conrelid='product_signal_history'::regclass
                   AND conname='product_signal_history_run_line_month_key') THEN
    ALTER TABLE product_signal_history ADD CONSTRAINT product_signal_history_run_line_month_key
      UNIQUE (run_id, product_line_code, month);
  END IF;
END $$;

-- Старые строки с NULL owner/quality остаются неизменными. Новые записи и правки
-- обязаны иметь известный запуск и честный интервал наблюдений, а не default=0.
CREATE OR REPLACE FUNCTION guard_product_signal_history() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE month_start timestamptz; month_end timestamptz;
BEGIN
  IF NEW.run_id IS NULL OR NEW.run_id <= 0 THEN
    RAISE EXCEPTION 'product history requires known positive run_id' USING ERRCODE='23514';
  END IF;
  IF NEW.month <> date_trunc('month', NEW.month::timestamp)::date THEN
    RAISE EXCEPTION 'product history month must be first day' USING ERRCODE='23514';
  END IF;
  IF NEW.sentiment_known_count IS NULL OR NEW.signal_count < 0
     OR NEW.negative_count < 0 OR NEW.negative_count > NEW.sentiment_known_count
     OR NEW.sentiment_known_count > NEW.signal_count
     OR NEW.critical_count < 0 OR NEW.critical_count > NEW.signal_count THEN
    RAISE EXCEPTION 'product history counts are inconsistent' USING ERRCODE='23514';
  END IF;
  month_start := NEW.month::timestamp AT TIME ZONE 'Europe/Moscow';
  month_end := (NEW.month + INTERVAL '1 month')::timestamp AT TIME ZONE 'Europe/Moscow';
  IF NEW.coverage_start IS NULL OR NEW.coverage_end IS NULL OR NEW.is_partial IS NULL
     OR NEW.coverage_start < month_start OR NEW.coverage_end > month_end
     OR NEW.coverage_start >= NEW.coverage_end
     OR NEW.is_partial IS DISTINCT FROM (NEW.coverage_start <> month_start OR NEW.coverage_end <> month_end) THEN
    RAISE EXCEPTION 'product history coverage is inconsistent' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS product_signal_history_guard ON product_signal_history;
CREATE TRIGGER product_signal_history_guard BEFORE INSERT OR UPDATE ON product_signal_history
FOR EACH ROW EXECUTE FUNCTION guard_product_signal_history();
COMMENT ON COLUMN product_signal_history.run_id IS 'NULL только для legacy неизвестного запуска; чтение только явным all';
COMMENT ON COLUMN product_signal_history.sentiment_known_count IS 'NULL legacy: качество неизвестно; unknown не считается neutral';
COMMENT ON COLUMN product_signal_history.loss_rub IS 'NULL: потери не наблюдались; synthetic history не выдумывает деньги';

-- T-121 / migration0015: durable Telegram transport после0014.
-- Операционная схема намеренно без FK в восстанавливаемый public baseline.
CREATE SCHEMA IF NOT EXISTS channel_runtime;
CREATE TABLE IF NOT EXISTS channel_runtime.telegram_conversations (
    bot_id bigint NOT NULL CHECK (bot_id > 0),
    chat_id bigint NOT NULL CHECK (chat_id > 0),
    state_enc bytea NOT NULL,
    revision bigint NOT NULL DEFAULT 0 CHECK (revision >= 0),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (bot_id, chat_id)
);
CREATE TABLE IF NOT EXISTS channel_runtime.telegram_inbound (
    bot_id bigint NOT NULL CHECK (bot_id > 0),
    update_id bigint NOT NULL CHECK (update_id >= 0),
    chat_id bigint NOT NULL CHECK (chat_id > 0),
    body_hash text NOT NULL CHECK (body_hash ~ '^[0-9a-f]{64}$'),
    response_enc bytea NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (bot_id, update_id)
);
-- Stable identity позволяет отличить восстановленную notification от новой с тем же id.
ALTER TABLE public.notifications ADD COLUMN IF NOT EXISTS delivery_key uuid NOT NULL DEFAULT gen_random_uuid();
CREATE UNIQUE INDEX IF NOT EXISTS notifications_delivery_key_uidx ON public.notifications (delivery_key);
CREATE TABLE IF NOT EXISTS channel_runtime.telegram_deliveries (
    delivery_key uuid PRIMARY KEY,
    bot_id bigint NOT NULL CHECK (bot_id > 0),
    chat_id bigint NOT NULL CHECK (chat_id > 0),
    notification_id bigint NOT NULL,
    run_id bigint NOT NULL,
    body_hash text NOT NULL CHECK (body_hash ~ '^[0-9a-f]{64}$'),
    payload_enc bytea NOT NULL,
    status text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','claimed','sent','failed','unknown','suppressed')),
    claimed_at timestamptz,
    completed_at timestamptz,
    external_ref text,
    error_code text,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (status <> 'sent' OR (external_ref IS NOT NULL AND completed_at IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS telegram_deliveries_queue_idx
    ON channel_runtime.telegram_deliveries (created_at, delivery_key) WHERE status = 'queued';
CREATE TABLE IF NOT EXISTS channel_runtime.telegram_chat_rate (
    bot_id bigint NOT NULL CHECK (bot_id > 0),
    chat_id bigint NOT NULL CHECK (chat_id > 0),
    last_claimed_at timestamptz NOT NULL,
    PRIMARY KEY (bot_id, chat_id)
);

-- Сеть могла принять sendMessage до потери ответа: это не definite failed/sent.
ALTER TABLE public.notifications DROP CONSTRAINT IF EXISTS notifications_status_check;
ALTER TABLE public.notifications ADD CONSTRAINT notifications_status_check
 CHECK (status IN ('queued','sent','delivered','failed','suppressed','unknown'));

ALTER TABLE channel_runtime.telegram_deliveries ADD COLUMN IF NOT EXISTS sent_sim timestamptz;

CREATE TABLE IF NOT EXISTS channel_runtime.telegram_signal_bindings (
    bot_id bigint NOT NULL CHECK (bot_id > 0),
    chat_id bigint NOT NULL CHECK (chat_id > 0),
    signal_id bigint NOT NULL,
    run_id bigint NOT NULL,
    token_hash text NOT NULL CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (bot_id, signal_id, run_id, token_hash)
);
CREATE TABLE IF NOT EXISTS channel_runtime.telegram_client_bindings (
    bot_id bigint NOT NULL CHECK (bot_id > 0),
    chat_id bigint NOT NULL CHECK (chat_id > 0),
    client_id bigint NOT NULL,
    client_code text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (bot_id, client_id),
    UNIQUE (bot_id, chat_id)
);

-- T-050: operational accounting survives bank seed/restore; no FK into public.
-- Stable configuration identity: numeric IDs can be reused after bank restore.
ALTER TABLE public.llm_profiles ADD COLUMN IF NOT EXISTS quota_uid uuid NOT NULL DEFAULT gen_random_uuid();
DO $$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='llm_profiles_quota_uid_key') THEN
  ALTER TABLE public.llm_profiles ADD CONSTRAINT llm_profiles_quota_uid_key UNIQUE (quota_uid);
 END IF;
END $$;
COMMENT ON COLUMN public.llm_profiles.quota_uid IS 'Private budget configuration identity; no API/AR/export projection; not usage';
CREATE SCHEMA IF NOT EXISTS llm_runtime;
CREATE TABLE IF NOT EXISTS llm_runtime.identity_settings (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    secret_tag bytea NOT NULL CHECK (octet_length(secret_tag) = 32),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS llm_runtime.credentials (
    uid uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    provider text NOT NULL CHECK (provider IN ('gigachat', 'openai_compatible')),
    verifier bytea UNIQUE NOT NULL CHECK (octet_length(verifier) = 32),
    confirmed_tokens bigint NOT NULL DEFAULT 0 CHECK (confirmed_tokens >= 0),
    legacy_tokens_hint bigint NOT NULL DEFAULT 0 CHECK (legacy_tokens_hint >= 0),
    usage_known boolean NOT NULL DEFAULT false,
    usage_source text NOT NULL DEFAULT 'unknown',
    usage_as_of timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS llm_runtime.credential_aliases (
    config_uid uuid PRIMARY KEY,
    credential_uid uuid NOT NULL REFERENCES llm_runtime.credentials(uid),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS llm_runtime.profile_scopes (
    scope text PRIMARY KEY,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS llm_runtime.daily_usage (
    scope_type text NOT NULL CHECK (scope_type IN ('key', 'profile')),
    scope_id text NOT NULL,
    utc_day date NOT NULL,
    requests_today bigint NOT NULL DEFAULT 0 CHECK (requests_today >= 0),
    requests_known boolean NOT NULL DEFAULT false,
    usage_source text NOT NULL DEFAULT 'unknown',
    usage_as_of timestamptz,
    PRIMARY KEY (scope_type, scope_id, utc_day)
);
CREATE TABLE IF NOT EXISTS llm_runtime.reconciliations (
    id uuid PRIMARY KEY,
    credential_uid uuid NOT NULL REFERENCES llm_runtime.credentials(uid),
    as_of timestamptz NOT NULL,
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    source text NOT NULL CHECK (source = 'operator_declared_app_usage'),
    observation jsonb NOT NULL CHECK (jsonb_typeof(observation) = 'object')
);
CREATE TABLE IF NOT EXISTS llm_runtime.wire_attempts (
    id uuid PRIMARY KEY,
    credential_uid uuid NOT NULL REFERENCES llm_runtime.credentials(uid),
    profile_scope text NOT NULL,
    profile_id integer,
    profile_code text NOT NULL,
    endpoint text NOT NULL,
    model text NOT NULL,
    utc_day date NOT NULL,
    admitted_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    deadline_at timestamptz NOT NULL,
    finished_at timestamptz,
    state text NOT NULL DEFAULT 'reserved' CHECK (state IN ('reserved', 'known', 'unknown', 'reconciled')),
    prompt_tokens bigint CHECK (prompt_tokens >= 0),
    completion_tokens bigint CHECK (completion_tokens >= 0),
    observed_tokens bigint NOT NULL DEFAULT 0 CHECK (observed_tokens >= 0),
    error_kind text,
    reconciliation_id uuid REFERENCES llm_runtime.reconciliations(id),
    CHECK (state <> 'known' OR (prompt_tokens IS NOT NULL AND completion_tokens IS NOT NULL AND finished_at IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS wire_attempts_key_day_idx
    ON llm_runtime.wire_attempts (credential_uid, utc_day, admitted_at);
CREATE INDEX IF NOT EXISTS wire_attempts_profile_day_idx
    ON llm_runtime.wire_attempts (profile_scope, utc_day, admitted_at);

-- Idempotent for a partially installed development checkpoint as well.
ALTER TABLE llm_runtime.wire_attempts ADD COLUMN IF NOT EXISTS profile_id integer;
ALTER TABLE llm_runtime.wire_attempts ADD COLUMN IF NOT EXISTS profile_code text NOT NULL DEFAULT '';

-- Normalize a pre-release partially installed checkpoint without changing history.
ALTER TABLE llm_runtime.wire_attempts ALTER COLUMN profile_code DROP DEFAULT;

-- T-161: durable behavior owner, evidence/receipts/timers; actual parent0016.
-- Legacy duplicate current states требуют явного согласования, без удаления истории.
DO $$ BEGIN
  IF EXISTS(SELECT 1 FROM client_states WHERE is_current GROUP BY run_id,client_id HAVING count(*)>1) THEN
    RAISE EXCEPTION 'legacy duplicate current client states: explicit operator reconciliation required' USING ERRCODE='23514';
  END IF;
END $$;
CREATE UNIQUE INDEX IF NOT EXISTS behavior_client_states_current_key ON client_states(run_id,client_id) WHERE is_current;

CREATE OR REPLACE FUNCTION valid_behavior_care_snapshot(doc jsonb) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE component text;
BEGIN
  IF jsonb_typeof(doc) IS DISTINCT FROM 'object'
     OR NOT doc ?& ARRAY['version','components','first_reply_at','tone_violated','sla_breached']
     OR (SELECT count(*) FROM jsonb_object_keys(doc))<>5
     OR doc->'version' IS DISTINCT FROM '1'::jsonb
     OR jsonb_typeof(doc->'components') IS DISTINCT FROM 'object'
     OR NOT (doc->'components') ?& ARRAY['proactive','speed','sla','gift_fit','tone','explanation']
     OR (SELECT count(*) FROM jsonb_object_keys(doc->'components'))<>6
     OR jsonb_typeof(doc->'tone_violated') IS DISTINCT FROM 'boolean'
     OR jsonb_typeof(doc->'sla_breached') IS DISTINCT FROM 'boolean'
     OR jsonb_typeof(doc->'first_reply_at') NOT IN ('string','null') THEN
    RETURN false;
  END IF;
  FOREACH component IN ARRAY ARRAY['proactive','speed','sla','gift_fit','tone','explanation'] LOOP
    IF jsonb_typeof(doc->'components'->component) IS DISTINCT FROM 'number' THEN RETURN false; END IF;
    IF (doc->'components'->>component)::numeric NOT BETWEEN 0 AND 1 THEN RETURN false; END IF;
  END LOOP;
  IF (doc->>'tone_violated')::boolean AND (doc->'components'->>'tone')::numeric<>0 THEN RETURN false; END IF;
  IF (doc->>'sla_breached')::boolean AND (doc->'components'->>'sla')::numeric<>0 THEN RETURN false; END IF;
  IF jsonb_typeof(doc->'first_reply_at')='string' THEN
    IF doc->>'first_reply_at' !~ '(Z|[+-][0-9]{2}:[0-9]{2})$' THEN RETURN false; END IF;
    PERFORM (doc->>'first_reply_at')::timestamptz;
  END IF;
  RETURN true;
END $$;

CREATE OR REPLACE FUNCTION behavior_valid_failed_operation(op_id bigint, expected_run bigint) RETURNS boolean
LANGUAGE sql STABLE AS $$
  SELECT EXISTS(
    SELECT 1 FROM operations o JOIN clients c ON c.id=o.client_id
    LEFT JOIN faults f ON f.id=o.fault_id
    WHERE o.id=op_id AND o.run_id=expected_run AND o.status='failed' AND o.error_code IS NOT NULL
      AND (o.fault_id IS NULL OR (f.run_id=o.run_id AND f.error_code=o.error_code
        AND f.system_code=ANY(o.system_path) AND o.started_sim>=f.started_sim
        AND (f.resolved_sim IS NULL OR o.started_sim<f.resolved_sim)
        AND (cardinality(f.region_codes)=0 OR c.region_code=ANY(f.region_codes))))
  );
$$;

CREATE TABLE IF NOT EXISTS behavior_evidence (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id bigint NOT NULL REFERENCES sim_runs(id) ON DELETE CASCADE,
  client_id bigint NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  source_kind text NOT NULL CHECK(source_kind IN ('operation','notification','twin_reaction','sla','resolution','agent_state')),
  source_id bigint NOT NULL CHECK(source_id>0),
  observed_sim timestamptz NOT NULL,
  consumed_sim timestamptz,
  UNIQUE(run_id,client_id,source_kind,source_id)
);
CREATE INDEX IF NOT EXISTS behavior_evidence_due_idx ON behavior_evidence(run_id,observed_sim,id) WHERE consumed_sim IS NULL;
CREATE TABLE IF NOT EXISTS behavior_runtime (
  run_id bigint NOT NULL REFERENCES sim_runs(id) ON DELETE CASCADE,
  client_id bigint NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  episode_no integer NOT NULL CHECK(episode_no>0),
  state_id bigint NOT NULL REFERENCES client_states(id),
  opened_sim timestamptz NOT NULL,
  closed_sim timestamptz,
  psychotype_code text NOT NULL,
  segment_code text NOT NULL,
  first_response_min integer NOT NULL CHECK(first_response_min>0),
  policy_source_sha256 text NOT NULL CHECK(policy_source_sha256 ~ '^[0-9a-f]{64}$'),
  policy_hash text NOT NULL CHECK(policy_hash ~ '^[0-9a-f]{64}$'),
  policy_snapshot jsonb NOT NULL,
  params_snapshot jsonb NOT NULL,
  care_snapshot jsonb NOT NULL CHECK(octet_length(care_snapshot::text)<=4096 AND valid_behavior_care_snapshot(care_snapshot)),
  first_complaint_sim timestamptz,
  patience_due_sim timestamptz NOT NULL,
  repeat_count integer NOT NULL DEFAULT 0 CHECK(repeat_count>=0),
  sla_breached boolean NOT NULL DEFAULT false,
  silent_decline boolean NOT NULL DEFAULT false,
  next_hazard_sim timestamptz NOT NULL,
  PRIMARY KEY(run_id,client_id)
);
CREATE TABLE IF NOT EXISTS behavior_causes (
  run_id bigint NOT NULL,
  client_id bigint NOT NULL,
  episode_no integer NOT NULL CHECK(episode_no>0),
  operation_id bigint NOT NULL REFERENCES operations(id),
  fault_id bigint REFERENCES faults(id),
  PRIMARY KEY(run_id,client_id,operation_id),
  FOREIGN KEY(run_id,client_id) REFERENCES behavior_runtime(run_id,client_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS behavior_work (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id bigint NOT NULL,
  client_id bigint NOT NULL,
  episode_no integer NOT NULL CHECK(episode_no>0),
  status text NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','consumed','cancelled')),
  kind text NOT NULL CHECK(kind IN ('complaint','repeat','patience')),
  source_id bigint NOT NULL CHECK(source_id>0),
  due_sim timestamptz NOT NULL,
  consumed_sim timestamptz,
  UNIQUE(run_id,client_id,episode_no,kind,source_id),
  FOREIGN KEY(run_id,client_id) REFERENCES behavior_runtime(run_id,client_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS behavior_work_due_idx ON behavior_work(run_id,due_sim,id) WHERE status='pending';
CREATE TABLE IF NOT EXISTS behavior_receipts (
  run_id bigint NOT NULL REFERENCES sim_runs(id) ON DELETE CASCADE,
  client_id bigint NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  source_kind text NOT NULL,
  source_id bigint NOT NULL CHECK(source_id>0),
  action text NOT NULL,
  consumed_sim timestamptz NOT NULL,
  PRIMARY KEY(run_id,client_id,source_kind,source_id,action)
);
CREATE TABLE IF NOT EXISTS behavior_tick_receipts (
  run_id bigint NOT NULL REFERENCES sim_runs(id) ON DELETE CASCADE,
  client_id bigint NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  logical_tick_sim timestamptz NOT NULL,
  PRIMARY KEY(run_id,client_id,logical_tick_sim)
);

-- Запрос агента хранится отдельно от результата owner; никаких inferred closure.
CREATE TABLE IF NOT EXISTS behavior_agent_intents (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id bigint NOT NULL REFERENCES sim_runs(id) ON DELETE CASCADE,
  agent_run_id bigint NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
  client_id bigint NOT NULL REFERENCES clients(id),
  signal_id bigint NOT NULL REFERENCES signals(id),
  incident_id bigint REFERENCES incidents(id),
  requested_state text NOT NULL CHECK(requested_state IN ('calm','affected','complaining','waiting','asks_again','escalates','satisfied','churn_intent','retained','churned')),
  trigger text NOT NULL CHECK(length(trigger) BETWEEN 1 AND 128),
  observed_sim timestamptz NOT NULL,
  UNIQUE NULLS NOT DISTINCT(run_id,agent_run_id,client_id,signal_id,incident_id,requested_state,trigger)
);

-- Только новые или действительно пустые run; legacy timers не восстанавливаем догадкой.
CREATE TABLE IF NOT EXISTS behavior_runs (
  run_id bigint PRIMARY KEY REFERENCES sim_runs(id) ON DELETE CASCADE,
  policy_hash text NOT NULL CHECK(length(policy_hash)=64),
  activated_sim timestamptz NOT NULL
);
CREATE TABLE IF NOT EXISTS behavior_pending_signals (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id bigint NOT NULL REFERENCES sim_runs(id) ON DELETE CASCADE,
  client_id bigint NOT NULL REFERENCES clients(id),
  due_sim timestamptz NOT NULL,
  client_snapshot jsonb NOT NULL CHECK(jsonb_typeof(client_snapshot)='object' AND octet_length(client_snapshot::text)<=16384),
  signal_type text NOT NULL,
  product_code text NOT NULL REFERENCES products(code),
  source_operation_id bigint REFERENCES operations(id) ON DELETE CASCADE,
  source_fault_id bigint REFERENCES faults(id) ON DELETE CASCADE,
  error_code text REFERENCES error_codes(code),
  system_code text REFERENCES systems(code),
  correlation_id uuid NOT NULL,
  consumed_sim timestamptz
);
CREATE INDEX IF NOT EXISTS behavior_pending_due_idx ON behavior_pending_signals(run_id,due_sim,id) WHERE consumed_sim IS NULL;

-- T-241: DDL18 после фактической0017, read-only cabinet facts и происхождение human audit.
-- Аддитивные поля: NULL означает неизвестный legacy actor, без backfill.
ALTER TABLE human_decisions ADD COLUMN IF NOT EXISTS actor_role text
  CHECK (actor_role IN ('cx_operator','cx_lead','product_manager','product_head','compliance_officer','bank_head','admin'));
ALTER TABLE incident_status_history ADD COLUMN IF NOT EXISTS actor_role text
  CHECK (actor_role IN ('cx_operator','cx_lead','product_manager','product_head','compliance_officer','bank_head','admin'));
-- Одна строка на сигнал, без incident join: счётчики не размножаются.
CREATE OR REPLACE VIEW v_cabinet_signal_facts AS
SELECT s.id,s.public_id,s.run_id,s.product_line_code,s.received_sim,s.sentiment,
  s.classification->>'criticality' AS criticality,
  coalesce(s.geo->>'region_code',c.region_code) AS region_code,
  s.channel_code,s.meta->>'source_platform' AS source_platform,
  s.client_id,s.flags,s.red_words,s.status,c.public_id AS client_public_id,
  s.classification->>'signal_type' AS signal_type
FROM signals s LEFT JOIN clients c ON c.id=s.client_id
-- Служебный proactive anchor не является обращением клиента. NULL legacy сохраняем.
WHERE s.origin IS DISTINCT FROM 'proactive';
-- Сначала distinct соответствия, затем сохранённая экономика: без compute/write.
CREATE OR REPLACE VIEW v_cabinet_incident_facts AS
SELECT x.product_line_code,i.id,i.run_id,i.created_sim,i.region_code,i.status,
  i.criticality,i.sla_due_sim,i.outcome_class,ie.potential_loss_rub,
  ie.prevented_loss_rub,ie.computed_at
FROM incidents i
LEFT JOIN (SELECT DISTINCT s.product_line_code,ic.incident_id,s.run_id
      FROM signals s JOIN incident_signals ic ON ic.signal_id=s.id
      WHERE s.product_line_code IS NOT NULL) x ON i.id=x.incident_id AND i.run_id=x.run_id
LEFT JOIN incident_economics ie ON ie.incident_id=i.id;
CREATE INDEX IF NOT EXISTS signals_cabinet_scope_time_idx
 ON signals(run_id,product_line_code,received_sim DESC,id DESC);
CREATE INDEX IF NOT EXISTS product_history_scope_month_idx
 ON product_signal_history(run_id,product_line_code,month DESC);
-- Downgrade удаляет только views/indexes. Аддитивные audit columns/values
-- сохраняются: откат кода не должен уничтожать происхождение ручных решений.

-- T-039 B: только provenance отмены; legacy NULL не восстанавливается догадкой.
ALTER TABLE public.behavior_receipts ADD COLUMN IF NOT EXISTS details jsonb;

CREATE OR REPLACE FUNCTION public.valid_behavior_cancellation_details(
  p_source_kind text, p_action text, p_consumed_sim timestamptz, p_doc jsonb
) RETURNS boolean LANGUAGE plpgsql STABLE AS $$
DECLARE
  key text;
  keys text[] := ARRAY['version','episode_no','work_kind','due_sim','cancellation_sim',
    'cancellation_observed_sim','first_complaint_sim_at_cancellation','complaint_observation_complete',
    'evidence_id','evidence_kind','evidence_source_id','canonical_signal_id','resolution_sim'];
  stamp_pattern text := '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?(Z|[+-][0-9]{2}:[0-9]{2})$';
BEGIN
  IF p_doc IS NULL THEN RETURN true; END IF;
  IF jsonb_typeof(p_doc) IS DISTINCT FROM 'object' OR octet_length(p_doc::text)>2048 THEN RETURN false; END IF;
  IF NOT (p_doc ?& keys) OR EXISTS(SELECT 1 FROM jsonb_object_keys(p_doc) k WHERE NOT k=ANY(keys)) THEN RETURN false; END IF;
  IF p_source_kind IS DISTINCT FROM 'work' OR p_action IS NULL OR p_action NOT IN ('cancelled_by_resolution','already_complained') THEN RETURN false; END IF;
  IF jsonb_typeof(p_doc->'version') IS DISTINCT FROM 'number' OR p_doc->>'version'<>'1' THEN RETURN false; END IF;
  FOREACH key IN ARRAY ARRAY['episode_no','evidence_id','evidence_source_id'] LOOP
    IF jsonb_typeof(p_doc->key) IS DISTINCT FROM 'number' THEN RETURN false; END IF;
    IF (p_doc->>key) !~ '^[1-9][0-9]*$' THEN RETURN false; END IF;
    IF (p_doc->>key)::numeric>9223372036854775807 THEN RETURN false; END IF;
  END LOOP;
  IF (p_doc->>'episode_no')::numeric>2147483647 THEN RETURN false; END IF;
  IF jsonb_typeof(p_doc->'canonical_signal_id') IS DISTINCT FROM 'null' THEN
    IF jsonb_typeof(p_doc->'canonical_signal_id') IS DISTINCT FROM 'number' THEN RETURN false; END IF;
    IF p_doc->>'canonical_signal_id' !~ '^[1-9][0-9]*$' THEN RETURN false; END IF;
    IF (p_doc->>'canonical_signal_id')::numeric>9223372036854775807 THEN RETURN false; END IF;
  END IF;
  IF p_doc->>'work_kind' NOT IN ('complaint','repeat','patience') OR
    jsonb_typeof(p_doc->'work_kind') IS DISTINCT FROM 'string' OR
    p_doc->>'evidence_kind' NOT IN ('resolution','agent_state') OR
    jsonb_typeof(p_doc->'evidence_kind') IS DISTINCT FROM 'string' OR
    jsonb_typeof(p_doc->'complaint_observation_complete') IS DISTINCT FROM 'boolean' THEN RETURN false; END IF;
  FOREACH key IN ARRAY ARRAY['due_sim','cancellation_sim','cancellation_observed_sim',
    'first_complaint_sim_at_cancellation','resolution_sim'] LOOP
    IF key IN ('first_complaint_sim_at_cancellation','resolution_sim') AND jsonb_typeof(p_doc->key)='null' THEN CONTINUE; END IF;
    IF jsonb_typeof(p_doc->key) IS DISTINCT FROM 'string' OR p_doc->>key !~ stamp_pattern THEN RETURN false; END IF;
    IF NOT pg_catalog.pg_input_is_valid(p_doc->>key,'timestamp with time zone') THEN RETURN false; END IF;
  END LOOP;
  IF (p_doc->>'cancellation_sim')::timestamptz IS DISTINCT FROM p_consumed_sim OR
    (p_doc->>'cancellation_observed_sim')::timestamptz<(p_doc->>'cancellation_sim')::timestamptz THEN RETURN false; END IF;
  FOREACH key IN ARRAY ARRAY['first_complaint_sim_at_cancellation','resolution_sim'] LOOP
    IF jsonb_typeof(p_doc->key)<>'null' AND (p_doc->>key)::timestamptz>(p_doc->>'cancellation_sim')::timestamptz THEN RETURN false; END IF;
  END LOOP;
  IF p_action='cancelled_by_resolution' THEN
    RETURN p_doc->>'evidence_kind'='resolution';
  END IF;
  RETURN p_doc->>'evidence_kind'='agent_state' AND p_doc->>'work_kind'='complaint'
    AND jsonb_typeof(p_doc->'canonical_signal_id')='number'
    AND jsonb_typeof(p_doc->'first_complaint_sim_at_cancellation')='string'
    AND jsonb_typeof(p_doc->'resolution_sim')='null';
END $$;

DO $$ BEGIN
  IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conrelid='public.behavior_receipts'::regclass AND conname='behavior_cancellation_details_valid') THEN
    ALTER TABLE public.behavior_receipts ADD CONSTRAINT behavior_cancellation_details_valid
      CHECK(public.valid_behavior_cancellation_details(source_kind,action,consumed_sim,details));
  END IF;
END $$;
COMMENT ON COLUMN public.behavior_receipts.details IS
  'T039 B v1: native provenance отмены; NULL остаётся неизвестным, без legacy backfill и attribution к Sent';


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
