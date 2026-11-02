import type { CabinetSignal, Overview } from '../api'

export const overview: Overview = {
  scope: { role: 'cx_lead', visibility: 'soft', product_lines: null, run_ids: [1], period: 'week', since_sim: '2026-11-02T06:00:00Z', sim_time: '2026-11-09T06:00:00Z' },
  product_lines: [{ code: 'deposits', name_ru: 'Вклады', name_en: 'Deposits', rate_code: 'deposit', owner_team_code: 'team_deposits', owner_is_proxy: false, product_codes: ['deposit'] }],
  kpi: { signals: 3, sentiment_known: 1, negative: 1, criticality_known: 2, critical: 1, mapped: 2, no_geo: 1, incidents: 1, economics_known: 0, potential_loss_rub: null, prevented_loss_rub: null, oldest_computed_at: null, negative_share: 1, critical_share: .5 },
  regions: [{ code: '77', name_ru: 'Москва', name_en: 'Moscow', lat: 55.75, lon: 37.62, signals: 2, negative: 1, critical: 1, affected_clients: 2, identified_clients: 2, identified_signals: 2, negativity_index: 1, zone: 'red', critical_count: 1, copilot_index: null, zone_index: 1 }],
  top_regions: [], sources: [{ platform: { code: 'client_voice', name_ru: 'Отзывы клиентов', name_en: 'Customer reviews', type: 'review_portal' }, signals: 2 }, { platform: null, signals: 1 }],
  daily: [{ day: '2026-11-09', signals: 3, incidents: 1, economics_known: 0, potential_loss_rub: null, prevented_loss_rub: null }],
  monthly: [{ month: '2026-10-01', signals: 10, sentiment_known: 4, negative: 2, critical: 1, potential_loss_rub: null, is_synthetic: true, is_partial: false, quality_unknown: false, coverage_start: '2026-09-30T21:00:00Z', coverage_end: '2026-10-31T21:00:00Z' }],
  csi: { responses: 1, branches: 1, branch_known: 1, wait_known: 0, average_wait_min: null }, history_note: 'synthetic_aggregates_and_observed_live_tail', economics_note: 'saved_incident_economics_only',
}
export const signal: CabinetSignal = {
  id: 7, public_id: 'SIG-000007', run_id: 1, product_line_code: 'deposits', received_sim: '2026-11-09T06:00:00Z', sentiment: 'negative', signal_type: 'complaint', criticality: 'high', region_code: '77', channel_code: 'review_portal', source_platform: overview.sources[0]!.platform, client_id: 2, client_public_id: 'CL-000002', flags: ['red_word'], red_words: ['суд'], status: 'classified', summary: 'Тестовая жалоба на условия вклада.', sla_due_sim: '2026-11-09T09:00:00Z', incidents: [{ id: 3, public_id: 'INC-000003', status: 'in_progress' }],
}
