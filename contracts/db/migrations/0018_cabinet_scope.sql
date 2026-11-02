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
FROM signals s LEFT JOIN clients c ON c.id=s.client_id;
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
