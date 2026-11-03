-- Read-only аудит всех запусков в одном statement snapshot, без текстов и контактов.
-- Проверяет сохранённые timestamps, а не смысл ответа или факт внешней доставки.
WITH notes AS (
  SELECT n.channel_code,count(*) AS sent_records,
    count(s.id) AS anchored_records,
    count(*) FILTER (WHERE s.id IS NULL) AS unknown_question,
    count(*) FILTER (WHERE s.id IS NOT NULL AND (n.sent_sim IS NULL OR s.received_sim IS NULL)) AS unknown_sim_time,
    count(*) FILTER (WHERE s.id IS NOT NULL AND (n.sent_at IS NULL OR s.received_at IS NULL)) AS unknown_real_time,
    count(*) FILTER (WHERE s.id IS NOT NULL AND n.sent_sim<s.received_sim) AS before_question_sim,
    count(*) FILTER (WHERE s.id IS NOT NULL AND n.sent_at<s.received_at) AS before_question_real,
    count(*) FILTER (WHERE s.id IS NOT NULL AND n.run_id<>s.run_id) AS foreign_run
  FROM notifications n LEFT JOIN signals s ON s.id=n.signal_id
  WHERE n.recipient_type='client' AND n.status IN ('sent','delivered') GROUP BY n.channel_code
), replies AS (
  SELECT count(*) AS records,count(p.id) AS anchored_records,
    count(*) FILTER (WHERE p.id IS NULL) AS unknown_question,
    count(*) FILTER (WHERE r.published_at<p.posted_at) AS before_question_real,
    count(*) FILTER (WHERE r.run_id<>p.run_id) AS foreign_run
  FROM external_replies r LEFT JOIN external_posts p ON p.id=r.post_id
), gifts AS (
  SELECT count(*) AS records,count(i.id) AS anchored_incidents,
    count(*) FILTER (WHERE h.first_sim IS NULL OR n.sent_sim IS NULL) AS unknown_resolution_sim,
    count(*) FILTER (WHERE n.sent_sim<h.first_sim) AS before_first_recorded_resolution_sim,
    count(*) FILTER (WHERE n.sent_at<h.first_real) AS before_first_recorded_resolution_real,
    count(*) FILTER (WHERE n.run_id<>i.run_id) AS foreign_run
  FROM notifications n LEFT JOIN incidents i ON i.id=n.incident_id
  LEFT JOIN LATERAL (
    SELECT min(changed_sim) AS first_sim,min(changed_at) AS first_real
    FROM incident_status_history WHERE incident_id=i.id AND to_status IN ('resolved','closed')
  ) h ON true
  WHERE n.recipient_type='client' AND n.template_code='gift_offer' AND n.status IN ('sent','delivered')
), children AS (
  SELECT count(*) AS records,count(p.id) AS anchored_records,
    count(*) FILTER (WHERE p.id IS NULL) AS unknown_parent,
    count(*) FILTER (WHERE s.received_sim<p.received_sim) AS before_parent_sim,
    count(*) FILTER (WHERE s.received_at<p.received_at) AS before_parent_real,
    count(*) FILTER (WHERE s.run_id<>p.run_id) AS foreign_run
  FROM signals s LEFT JOIN signals p ON p.id=s.parent_signal_id WHERE s.parent_signal_id IS NOT NULL
)
SELECT jsonb_build_object(
  'scope','all_runs',
  'coverage','stored_timestamp_invariants_only',
  'delivery_semantics','stored_sent_or_delivered; not proof of external delivery',
  'notifications',coalesce((SELECT jsonb_agg(to_jsonb(n) ORDER BY channel_code) FROM notes n),'[]'::jsonb),
  'public_replies',(SELECT to_jsonb(r) FROM replies r),
  'gift_notices',(SELECT to_jsonb(g) FROM gifts g),
  'client_replies',(SELECT to_jsonb(c) FROM children c),
  'known_invariants_passed',NOT EXISTS (
    SELECT 1 FROM notes WHERE before_question_sim>0 OR before_question_real>0 OR foreign_run>0
  ) AND NOT EXISTS (
    SELECT 1 FROM gifts WHERE before_first_recorded_resolution_sim>0 OR before_first_recorded_resolution_real>0 OR foreign_run>0
  ) AND NOT EXISTS (
    SELECT 1 FROM replies WHERE before_question_real>0 OR foreign_run>0
  ) AND NOT EXISTS (
    SELECT 1 FROM children WHERE before_parent_sim>0 OR before_parent_real>0 OR foreign_run>0
  )
);
