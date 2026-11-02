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
