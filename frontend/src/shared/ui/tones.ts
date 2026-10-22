export type Tone = 'neutral' | 'ok' | 'warn' | 'danger' | 'info' | 'brand'

export function criticalityTone(c: string | null | undefined): Tone {
  return c === 'high' ? 'danger' : c === 'medium' ? 'warn' : 'neutral'
}
export function sentimentTone(s: string | null | undefined): Tone {
  return s === 'negative' ? 'danger' : s === 'positive' ? 'ok' : 'neutral'
}
export function severityTone(s: string | null | undefined): Tone {
  return s === 'critical' ? 'danger' : s === 'high' ? 'danger' : s === 'medium' ? 'warn' : 'neutral'
}
export function incidentStatusTone(s: string | null | undefined): Tone {
  switch (s) {
    case 'resolved':
    case 'closed':
    case 'fix_deployed':
      return 'ok'
    case 'escalated':
    case 'rejected':
      return 'danger'
    case 'awaiting_human':
    case 'awaiting_client':
    case 'verifying':
    case 'fix_proposed':
      return 'warn'
    case 'in_progress':
    case 'routed':
      return 'info'
    default:
      return 'neutral'
  }
}
export function signalStatusTone(s: string | null | undefined): Tone {
  switch (s) {
    case 'answered':
    case 'closed':
      return 'ok'
    case 'awaiting_human':
      return 'warn'
    case 'processing':
      return 'info'
    case 'rejected':
      return 'danger'
    default:
      return 'neutral'
  }
}
