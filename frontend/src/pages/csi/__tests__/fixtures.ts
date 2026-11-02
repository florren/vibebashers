import type { CsiAnalytics } from '../api'
export const snapshot: CsiAnalytics = {
  scope: { role: 'cx_lead', visibility: 'soft', product_lines: null, run_ids: [19], period: 'month', since_sim: '2026-10-02T06:00:00Z', sim_time: '2026-11-02T06:00:00Z', branch_id: null, region_code: null },
  coverage: { complaints: 1, branch_known: 1, direction_known: 0, employee_known: 0, cohort_bound: 0, scatter_total: 1, uncohorted: 1, time_basis: 'native_received_sim' },
  complaints: { items: [{ signal_ref: 'SIG-000007', csi_no: 'CSI-030001', received_sim: '2026-11-01T06:00:00Z', response_at: null, branch_id: 42, branch_code: '0041', region_code: '77', product_line_code: null, direction_source: 'unknown', position: null, wait_min: 5, service_min: 12, redirects: null, criticality: null, summary: 'Тестовая жалоба' }], total: 1, next_offset: null },
  scatter: { items: [{ signal_ref: 'SIG-000007', wait_min: 5, service_min: 12, criticality: null, branch_code: '0041' }], total: 1, shown: 1, has_more: false },
  positions: [{ position: null, complaints: 1, known_employees: 0, anonymous_complaints: 1 }],
  tenure: { groups: [{ group: 'with_complaints', employees: 0, known_tenure: 0, minimum: null, q1: null, median: null, q3: null, maximum: null }, { group: 'without_complaints', employees: 2, known_tenure: 2, minimum: 0, q1: 2.5, median: 5, q3: 7.5, maximum: 10 }], unit: 'days', as_of_sim: '2026-11-02T06:00:00Z', population: 'current_active_branch_roster' },
  heatmap: [{ region_code: '77', complaints: 1 }], top_branches: [{ branch_id: 42, branch_code: '0041', branch_name: 'ВСП', region_code: '77', complaints: 1, average_wait_min: 5 }],
  probabilities: { overlapping_cohorts: 0, incomplete_cohorts: 0, partial_window_cohorts: 0, complete_cohorts: 0, synthetic: null, sample_complaints: null, sample_visits: null, time_basis: 'cohort_response_at', scope: 'registered_complete_cohorts', legacy_denominators_usable: false, mixed_sources: false, wait: { buckets: [{ bucket: '0-5', complaints: null, visits: null, probability: null }], spearman: null, n_buckets: 0 }, redirects: { buckets: [{ bucket: '0', complaints: null, visits: null, probability: null }], spearman: null, n_buckets: 0 } },
}
