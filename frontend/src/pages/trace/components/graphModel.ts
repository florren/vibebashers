import type { Trace, TraceEvent, TraceRelationPage } from '@/shared/api/trace'

export type NodeFamily = 'signal' | 'incident' | 'client' | 'action' | 'money' | 'message'
export type GraphNode = {
  id: string
  phase: TraceEvent['phase']
  family: NodeFamily
  title: string
  ref: string
  x: number
  y: number
  event?: TraceEvent
}
export const NODE_WIDTH = 216
export const NODE_HEIGHT = 76
export const COLUMN_GAP = 340
export const ROW_GAP = 112

export function nodeFamily(kind: string): NodeFamily {
  if (kind.startsWith('signal')) return 'signal'
  if (kind.startsWith('incident')) return 'incident'
  if (kind.startsWith('client') || kind === 'churn') return 'client'
  if (['refund', 'fee', 'economics', 'ledger', 'operation'].includes(kind)) return 'money'
  if (['notification', 'public_reply', 'source_message', 'post'].includes(kind)) return 'message'
  return 'action'
}

/** Ребро не создаёт сущность: единственный отсутствующий endpoint может быть subject,
 * поскольку assembler фильтрует рёбра по subject и полным before/after массивам.
 * Несколько неизвестных endpoints не сопоставляются, включая legacy/некорректные ответы. */
export function buildGraph(trace: Trace, page?: TraceRelationPage) {
  const raw = [...trace.before, ...trace.after]
  const known = new Set(raw.map((event) => event.id))
  const anchors = new Set(trace.groups.flatMap((group) =>
    group.anchor?.kind === trace.subject.kind && group.anchor.ref === trace.subject.ref ? [group.anchor.event_id] : [],
  ))
  const unknown = new Set(trace.edges.flatMap((edge) => [edge.from, edge.to]).filter((id) => !known.has(id)))
  const anchor = anchors.size === 1 ? [...anchors][0] : undefined
  const alias = anchor && (!unknown.size || [...unknown].every((id) => id === anchor))
    ? anchor
    : !anchors.size && unknown.size === 1 ? [...unknown][0] : undefined
  const subjectId = alias ?? `subject:${trace.subject.kind}:${trace.subject.ref}`
  const events = new Map(raw.map((event) => [event.id, event]))
  for (const event of page?.items ?? []) events.set(event.id, event)
  const counts = { before: 0, subject: 0, after: 0 }
  const nodes: GraphNode[] = [{
    id: subjectId, phase: 'subject', family: nodeFamily(trace.subject.kind), title: trace.subject.title_ru,
    ref: trace.subject.ref, x: 32 + COLUMN_GAP, y: 56,
  }]
  for (const event of events.values()) {
    if (event.id === subjectId) continue
    const phase = event.phase
    nodes.push({ id: event.id, phase, family: nodeFamily(event.kind), title: event.title_ru,
      ref: event.object_ref?.ref ?? '', event, x: 32 + (phase === 'before' ? 0 : phase === 'subject' ? 1 : 2) * COLUMN_GAP,
      y: 56 + counts[phase]++ * ROW_GAP })
  }
  const ids = new Set(nodes.map((node) => node.id))
  const sourceEdges = [...trace.edges, ...(page?.edges ?? [])]
  const hiddenEdges = sourceEdges.filter((edge) => !ids.has(edge.from) || !ids.has(edge.to)).length
  const edges = [...new Map(sourceEdges
    .filter((edge) => ids.has(edge.from) && ids.has(edge.to))
    .map((edge) => [`${edge.from}\0${edge.to}\0${edge.relation_ru}`, edge])).values()]
  const terminalId = trace.terminal.event_ref && ids.has(trace.terminal.event_ref) ? trace.terminal.event_ref : undefined
  const path = directedPath(edges, subjectId, terminalId)
  const reversePath = [...path]
  const pathEdges = new Set(reversePath.slice(1).map((id, index) => `${id}\0${reversePath[index]}`))
  return { nodes, edges, hiddenEdges, subjectId, terminalId, path, pathEdges, unresolved: !alias && unknown.size > 0,
    width: COLUMN_GAP * 2 + NODE_WIDTH + 64,
    height: Math.max(240, 100 + Math.max(...Object.values(counts), 1) * ROW_GAP) }
}

export function directedPath(edges: Trace['edges'], start: string, end?: string) {
  if (!end) return new Set<string>()
  const adjacent = new Map<string, string[]>()
  for (const edge of edges) {
    const targets = adjacent.get(edge.from) ?? []
    targets.push(edge.to)
    adjacent.set(edge.from, targets)
  }
  const prev = new Map<string, string | null>([[start, null]])
  const queue = [start]
  for (let i = 0; i < queue.length && !prev.has(end); i++) {
    for (const next of adjacent.get(queue[i]!) ?? []) {
      if (!prev.has(next)) { prev.set(next, queue[i]!); queue.push(next) }
    }
  }
  if (!prev.has(end)) return new Set<string>()
  const path = new Set<string>()
  for (let at: string | null = end; at != null; at = prev.get(at) ?? null) path.add(at)
  return path
}

export function nodeInViewport(node: GraphNode, view: { left: number; top: number; width: number; height: number }, zoom: number) {
  const margin = 120
  return node.x + NODE_WIDTH >= view.left / zoom - margin && node.x <= (view.left + view.width) / zoom + margin &&
    node.y + NODE_HEIGHT >= view.top / zoom - margin && node.y <= (view.top + view.height) / zoom + margin
}
