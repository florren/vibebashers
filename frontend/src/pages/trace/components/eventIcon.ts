import type { TraceEvent } from '@/shared/api/trace'

// The exhaustive switch covers the generated contract, including detail-only events.
export function eventIcon(kind: TraceEvent['kind']): string {
  switch (kind) {
    case 'signal_created':
    case 'signal_normalized':
      return '◉'
    case 'incident_created':
    case 'incident_linked':
    case 'incident_status':
      return '◆'
    case 'human_request':
    case 'human_decision':
      return '♙'
    case 'notification':
    case 'public_reply':
      return '✉'
    case 'refund':
    case 'fee':
    case 'economics':
      return '₽'
    case 'decision':
    case 'classification':
    case 'client_identified':
    case 'rule_evaluation':
    case 'policy_check':
    case 'tool_call':
      return '⚙'
    case 'source_message':
    case 'operation':
    case 'fault':
    case 'escalation':
    case 'team_action':
    case 'task':
    case 'followup':
    case 'client_reaction':
    case 'gift':
    case 'terminal':
    case 'churn':
    case 'zone_changed':
    case 'compliance_alert':
      return '•'
    default: {
      const exhaustive: never = kind
      return exhaustive
    }
  }
}
