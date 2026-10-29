import type { AgentRunDetail, AgentStep } from '@/shared/api/client'
import type { TraceEvent } from '@/shared/api/trace'
import { Product, Team } from '@/shared/contracts/enums'

export type StepSelection = { runId: number; node?: string; seq?: number }
export type NodeStatus = 'pending' | 'running' | 'done' | 'fallback' | 'error' | 'waiting_human' | 'scheduled' | 'skipped' | 'not_reached'
export function eventStep(event: TraceEvent): { runId: number; seq: number } | null {
  const link = event.links.engine_step
  const match = link?.match(/^\/engine\/(\d+)\?([^#]*)/)
  if (!match) return null
  const runId = Number(match[1]),
    seq = Number(new URLSearchParams(match[2]).get('step'))
  return Number.isSafeInteger(runId) && runId > 0 && Number.isSafeInteger(seq) && seq > 0 ? { runId, seq } : null
}
const resultKinds: Record<string, string> = {
  incident_id: 'incident',
  notification_id: 'notification',
  human_decision_id: 'human_decision',
  task_id: 'task',
  followup_id: 'followup',
  escalation_id: 'escalation',
  ledger_entry_id: 'ledger',
  ledger_id: 'ledger',
  entry_id: 'ledger',
}
const writes = new Set([
  'create_incident',
  'route_to_department',
  'route_to_product_team',
  'notify_customer',
  'notify_client',
  'notify_team',
  'link_signal_to_incident',
  'update_incident',
  'close_incident',
  'request_clarification',
  'request_human_decision',
  'create_task',
  'schedule_followup',
  'escalate_to_manager',
  'refund_fee',
])
export function relatedEvents(events: TraceEvent[], runId: number, step: AgentStep | undefined): TraceEvent[] {
  if (step?.seq == null) return []
  const objects = new Set<string>()
  for (const call of step.tool_calls ?? []) {
    if (!writes.has(call.name ?? '') || !call.result || typeof call.result !== 'object' || Array.isArray(call.result)) continue
    for (const [key, kind] of Object.entries(resultKinds)) {
      const id = (call.result as Record<string, unknown>)[key]
      if (typeof id === 'number' && Number.isSafeInteger(id) && id > 0) objects.add(`${kind}:${id}`)
    }
  }
  return events.filter((event) => {
    const direct = eventStep(event)
    if (direct) return direct.runId === runId && direct.seq === step.seq
    const object = event.object_ref
    // Ссылка на инцидент не доказывает принадлежность всей его последующей истории этому шагу.
    if (object?.kind === 'incident' && !['incident_created', 'incident_linked'].includes(event.kind)) return false
    if (object?.kind === 'human_decision' && event.kind !== 'human_request') return false
    const id = object?.ref.match(/^(?:[A-Z]+-)?(\d+)$/i)?.[1]
    return !!object && !!id && objects.has(`${object.kind}:${Number(id)}`)
  })
}
export function selectedAttempt(run: AgentRunDetail | undefined, selection: StepSelection | null): AgentStep | undefined {
  if (!run || !selection || selection.runId !== run.id) return undefined
  return selection.seq != null ? run.steps?.find((s) => s.seq === selection.seq) : run.steps?.filter((s) => s.node === selection.node).at(-1)
}
export function nodeStatus(run: AgentRunDetail | undefined, node: string, current: string | null): NodeStatus {
  if (current === node && (!run?.outcome || run.outcome === 'awaiting_human')) return run?.outcome === 'awaiting_human' ? 'waiting_human' : 'running'
  const step = run?.steps?.filter((s) => s.node === node).at(-1)
  if (step) {
    if (node === 'wait_human' && run?.outcome === 'awaiting_human') return 'waiting_human'
    if (node === 'followup_monitor' && run?.outcome === 'deferred') return 'scheduled'
    return step.status === 'error' ? 'error' : step.status === 'fallback' ? 'fallback' : 'done'
  }
  return run?.outcome === 'completed' || run?.outcome === 'fallback_mock' ? 'skipped' : run?.outcome === 'failed' ? 'not_reached' : 'pending'
}
/** Только записанные соседние шаги, без вывода рёбер из множества посещённых узлов. */
export function observedEdges(steps: AgentStep[]): Set<string> {
  const ordered = [...steps].sort((a, b) => (a.seq ?? 0) - (b.seq ?? 0)),
    edges = new Set<string>()
  for (let i = 1; i < ordered.length; i++) {
    const a = ordered[i - 1]!,
      b = ordered[i]!
    if (a.node && b.node && a.node !== b.node && a.seq != null && b.seq === a.seq + 1) edges.add(`${a.node}>${b.node}`)
  }
  return edges
}
/** В UI не попадают произвольные output/reasoning/промпты; только проверенные бизнес-коды и числа. */
export function stepFacts(step: AgentStep | undefined): { label: string; value: string | number | null }[] {
  const output = step?.output ?? {},
    facts: { label: string; value: string | number | null }[] = []
  const product = Object.hasOwn(output, 'product') ? output.product : (output.entities as Record<string, unknown> | undefined)?.product
  if (product === null || Object.hasOwn(output, 'product') || product !== undefined) {
    if (product == null) facts.push({ label: 'product', value: null })
    else if (Object.values(Product).some((p) => p === product)) facts.push({ label: 'product', value: product as string })
  }
  const routed = (output.route as Record<string, unknown> | undefined)?.team
  const team = routed ?? (output.problem_summary as Record<string, unknown> | undefined)?.suggested_team
  if (Object.values(Team).some((t) => t === team)) facts.push({ label: routed ? 'team' : 'suggestedTeam', value: team as string })
  if (typeof output.confidence === 'number' && output.confidence >= 0 && output.confidence <= 1)
    facts.push({ label: 'confidence', value: Math.round(output.confidence * 100) })
  if (['positive', 'neutral', 'negative'].includes(String(output.sentiment))) facts.push({ label: 'sentiment', value: String(output.sentiment) })
  if (['route', 'escalate', 'request_clarification', 'none'].includes(String(output.router_action)))
    facts.push({ label: 'action', value: String(output.router_action) })
  if (step?.tool_calls?.length) facts.push({ label: 'tools', value: step.tool_calls.length })
  return facts
}
