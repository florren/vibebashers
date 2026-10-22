import { clsx } from 'clsx'
import type { AgentGraph } from '@/shared/api/client'
import { tEnum } from '@/shared/i18n'

const W = 150
const H = 44
const GX = 28
const GY = 48
const PER_ROW = 5

/**
 * Статическая схема графа агента (SVG): основная цепочка «змейкой» по 5 узлов в ряд, ветка HITL (wait_human → apply_human_decision)
 * отдельным рядом под decide. Подсветка: пройденные узлы и рёбра — зелёные, текущий — пульсирует.
 * Без React Flow (решение B15: меньше бандл, детерминированная раскладка, SVG масштабируется через viewBox).
 */
export function GraphView({ graph, visited, current, outcome }: { graph: AgentGraph; visited: Set<string>; current: string | null; outcome: string | null }) {
  const nodes = graph.nodes ?? []
  const edges = graph.edges ?? []
  // Боковые узлы (HITL, отложенный мониторинг, проверка фикса) — отдельным рядом под своим предшественником.
  const isSide = (n: { id?: string; kind?: string }) => n.kind === 'human' || n.kind === 'scheduled' || n.id === 'verify'
  const main = nodes.filter((n) => !isSide(n))
  const rows = Math.ceil(main.length / PER_ROW)
  const pos = new Map<string, { x: number; y: number }>()
  main.forEach((n, i) => pos.set(n.id!, { x: 16 + (i % PER_ROW) * (W + GX), y: 16 + Math.floor(i / PER_ROW) * (H + GY) }))
  const sideY = 16 + rows * (H + GY)
  for (const n of nodes.filter(isSide)) {
    const pred = edges.find((e) => e.to === n.id)?.from ?? ''
    const pp = pos.get(pred)
    const predIsSide = nodes.some((m) => m.id === pred && isSide(m))
    pos.set(n.id!, { x: pp ? pp.x + (predIsSide ? W + GX : 0) : 16, y: sideY })
  }
  const width = 16 + PER_ROW * (W + GX)
  const height = sideY + H + 16

  const path = (a: string, b: string) => {
    const p = pos.get(a)
    const q = pos.get(b)
    if (!p || !q) return ''
    if (p.y === q.y && q.x > p.x) return `M${p.x + W},${p.y + H / 2} L${q.x},${q.y + H / 2}`
    const sx = p.x + W / 2
    const sy = p.y + (q.y > p.y ? H : 0)
    const tx = q.x + W / 2
    const ty = q.y + (q.y > p.y ? 0 : H)
    return `M${sx},${sy} C${sx},${(sy + ty) / 2} ${tx},${(sy + ty) / 2} ${tx},${ty}`
  }

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="block h-auto w-full max-w-[1100px]" role="img" aria-label="agent graph">
      <defs>
        <marker id="arr" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M0,0 L8,4 L0,8 z" className="fill-faint" />
        </marker>
      </defs>
      {edges.map((e, i) => {
        const on = visited.has(e.from ?? '') && visited.has(e.to ?? '')
        const p = pos.get(e.from ?? '')
        const q = pos.get(e.to ?? '')
        if (!p || !q) return null
        return (
          <g key={i}>
            <path d={path(e.from!, e.to!)} fill="none" strokeWidth={on ? 2 : 1.2} markerEnd="url(#arr)" className={on ? 'stroke-brand' : 'stroke-line'} />
            {e.condition && p.y !== q.y && (
              <text
                className="fill-faint text-[9px]"
                x={(p.x + W / 2 + q.x + W / 2) / 2}
                y={(p.y + q.y) / 2 + H / 2 + (p.y === q.y ? -8 : 4)}
                textAnchor="middle"
              >
                {e.condition}
              </text>
            )}
          </g>
        )
      })}
      {nodes.map((n) => {
        const p = pos.get(n.id!)
        if (!p) return null
        const isCur = current === n.id && outcome !== 'completed'
        const done = visited.has(n.id!)
        return (
          <g key={n.id} transform={`translate(${p.x},${p.y})`}>
            <rect
              width={W}
              height={H}
              rx={10}
              className={clsx('stroke-[1.5]', isCur ? 'fill-brand-soft stroke-brand' : done ? 'fill-surface stroke-brand' : 'fill-surface stroke-line')}
            />
            {isCur && <rect width={W} height={H} rx={10} className="animate-pulse fill-none stroke-brand" strokeWidth={3} />}
            <text x={12} y={18} className={clsx('text-[11.5px] font-medium', done || isCur ? 'fill-ink' : 'fill-muted')}>
              {tEnum('engine.node', n.id)}
            </text>
            <text x={12} y={33} className="fill-faint font-mono text-[9.5px]">
              {n.id} · {n.kind}
            </text>
          </g>
        )
      })}
    </svg>
  )
}
