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
