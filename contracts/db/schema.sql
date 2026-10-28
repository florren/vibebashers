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
  table_name  text        NOT NULL,
  op          text        NOT NULL CHECK (op IN ('INSERT','UPDATE','DELETE')),
  pk          text        NOT NULL,
  summary     jsonb,                                  -- короткая выжимка изменённых полей
  ts          timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE db_activity_log IS 'Лента INSERT/UPDATE/DELETE для демонстрации работы агента с БД';
CREATE INDEX db_activity_log_ts_idx ON db_activity_log (ts DESC);

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
  status           text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','sent','delivered','failed','suppressed')),
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
