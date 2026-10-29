import type { TraceEvent } from '@/shared/api/trace'

/** Часы не смешиваются: ts_sim и ts_real могут отличаться на дни. */
export function elapsedSeconds(events: TraceEvent[], clock: 'ts_real' | 'ts_sim'): number | null {
  const times = events.map((e) => Date.parse(e[clock] ?? '')).filter((n) => Number.isFinite(n) && n > 0)
  return times.length ? Math.max(0, Math.round((Math.max(...times) - Math.min(...times)) / 1000)) : null
}

export const NODE_STAGE: Record<string, string> = {
  ingest: 'intake',
  normalize: 'understanding',
  classify: 'understanding',
  identify_client: 'identity',
  gather_context: 'identity',
  check_rules: 'rules',
  decide: 'decision',
  instant_decide: 'decision',
  twin_react: 'client_outcome',
  wait_human: 'decision',
  apply_human_decision: 'decision',
  act: 'action',
  act_instant: 'action',
  followup_monitor: 'execution',
  verify: 'execution',
  close: 'client_outcome',
  gift: 'client_outcome',
}
