import { clsx } from 'clsx'
import { useId } from 'react'
import { useTranslation } from 'react-i18next'
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
export function GraphView({
  graph,
  visited,
  current,
  outcome,
  failed = new Set<string>(),
  compact = false,
  selectedNode,
  onNodeSelect,
  nodeDetails = {},
  takenEdges,
}: {
  selectedNode?: string | null
  onNodeSelect?: (node: string) => void
  nodeDetails?: Record<string, { status: string; detail?: string; result?: string }>
  takenEdges?: Set<string>
  failed?: Set<string>
  compact?: boolean
  graph: AgentGraph
  visited: Set<string>
  current: string | null
  outcome: string | null
}) {
  const { t } = useTranslation()
  const markerId = useId().replace(/:/g, '')
  const nodeHeight = onNodeSelect ? 64 : H
  const rowGap = compact ? 24 : GY
  const nodes = graph.nodes ?? []
  const edges = graph.edges ?? []
  // Боковые узлы (HITL, отложенный мониторинг, проверка фикса) — отдельным рядом под своим предшественником.
  const isSide = (n: { id?: string; kind?: string }) => n.kind === 'human' || n.kind === 'scheduled' || n.id === 'verify'
  const main = nodes.filter((n) => !isSide(n))
  const rows = Math.ceil(main.length / PER_ROW)
  const pos = new Map<string, { x: number; y: number }>()
  main.forEach((n, i) => pos.set(n.id!, { x: 16 + (i % PER_ROW) * (W + GX), y: 16 + Math.floor(i / PER_ROW) * (nodeHeight + rowGap) }))
  const sideY = 16 + rows * (nodeHeight + rowGap)
  for (const n of nodes.filter(isSide)) {
    const pred = edges.find((e) => e.to === n.id)?.from ?? ''
    const pp = pos.get(pred)
    const predIsSide = nodes.some((m) => m.id === pred && isSide(m))
    pos.set(n.id!, { x: pp ? pp.x + (predIsSide ? W + GX : 0) : 16, y: sideY })
  }
  const width = 16 + PER_ROW * (W + GX)
  const height = sideY + nodeHeight + 16

  const path = (a: string, b: string) => {
    const p = pos.get(a)
    const q = pos.get(b)
    if (!p || !q) return ''
    if (p.y === q.y && q.x > p.x) return `M${p.x + W},${p.y + nodeHeight / 2} L${q.x},${q.y + nodeHeight / 2}`
    const sx = p.x + W / 2
    const sy = p.y + (q.y > p.y ? nodeHeight : 0)
    const tx = q.x + W / 2
    const ty = q.y + (q.y > p.y ? 0 : nodeHeight)
    return `M${sx},${sy} C${sx},${(sy + ty) / 2} ${tx},${(sy + ty) / 2} ${tx},${ty}`
  }

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className={clsx('block h-auto w-full max-w-[1100px]', onNodeSelect && 'min-w-[760px]')}
      role={onNodeSelect ? 'group' : 'img'}
      aria-label={t('engine.graph')}
    >
      <defs>
        <marker id={markerId} viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M0,0 L8,4 L0,8 z" className="fill-faint" />
        </marker>
      </defs>
      {edges.map((e, i) => {
        const on = takenEdges ? takenEdges.has(`${e.from}>${e.to}`) : visited.has(e.from ?? '') && visited.has(e.to ?? '')
        const p = pos.get(e.from ?? '')
        const q = pos.get(e.to ?? '')
        if (!p || !q) return null
        return (
          <g key={i}>
            <path
              d={path(e.from!, e.to!)}
              fill="none"
              strokeWidth={on ? 2 : 1.2}
              markerEnd={`url(#${markerId})`}
              className={on ? 'stroke-brand' : 'stroke-line'}
            />
            {e.condition && p.y !== q.y && (
              <text
                className="fill-faint text-[9px]"
                x={(p.x + W / 2 + q.x + W / 2) / 2}
                y={(p.y + q.y) / 2 + nodeHeight / 2 + (p.y === q.y ? -8 : 4)}
                textAnchor="middle"
              >
                {onNodeSelect ? t(`journeyGraph.edge.${e.condition}`, { defaultValue: e.condition }) : e.condition}
              </text>
            )}
          </g>
        )
      })}
      {nodes.map((n) => {
        const p = pos.get(n.id!)
        if (!p) return null
        const isCur = current === n.id && (outcome == null || outcome === 'awaiting_human')
        const done = visited.has(n.id!)
        const error = failed.has(n.id!)
        return (
          <g
            key={n.id}
            transform={`translate(${p.x},${p.y})`}
            role={onNodeSelect ? 'button' : undefined}
            tabIndex={onNodeSelect ? 0 : undefined}
            aria-label={onNodeSelect ? `${tEnum('engine.node', n.id)} · ${nodeDetails[n.id!]?.status ?? ''}` : undefined}
            aria-pressed={onNodeSelect ? selectedNode === n.id : undefined}
            className={onNodeSelect ? 'group cursor-pointer outline-none' : undefined}
            onClick={() => onNodeSelect?.(n.id!)}
            onKeyDown={(e) => {
              if (onNodeSelect && (e.key === 'Enter' || e.key === ' ')) {
                e.preventDefault()
                onNodeSelect(n.id!)
              }
            }}
          >
            <title>{`${tEnum('engine.node', n.id)} · ${nodeDetails[n.id!]?.status ?? ''} · ${nodeDetails[n.id!]?.result ?? ''}`}</title>
            <rect
              width={W}
              height={nodeHeight}
              rx={10}
              className={clsx(
                selectedNode === n.id ? 'stroke-[3]' : 'stroke-[1.5] group-focus-visible:stroke-[3] group-focus-visible:stroke-brand',
                selectedNode === n.id
                  ? 'fill-brand-soft stroke-brand'
                  : error
                    ? 'fill-surface stroke-danger'
                    : isCur
                      ? 'fill-brand-soft stroke-brand'
                      : done
                        ? 'fill-surface stroke-brand'
                        : 'fill-surface stroke-line',
              )}
            />
            {isCur && <rect width={W} height={nodeHeight} rx={10} className="animate-pulse fill-none stroke-brand" strokeWidth={3} />}
            <text x={12} y={18} className={clsx('text-[11.5px] font-medium', done || isCur ? 'fill-ink' : 'fill-muted')}>
              {tEnum('engine.node', n.id)}
            </text>
            <text x={12} y={33} className="fill-muted font-mono text-[9.5px]">
              {onNodeSelect
                ? `${nodeDetails[n.id!]?.status ?? ''}${nodeDetails[n.id!]?.detail ? ` · ${nodeDetails[n.id!]?.detail}` : ''}`
                : `${n.id} · ${n.kind}`}
            </text>
            {onNodeSelect && (
              <text x={12} y={49} className="fill-muted text-[9.5px]">
                {(nodeDetails[n.id!]?.result ?? '').slice(0, 25)}
              </text>
            )}
          </g>
        )
      })}
    </svg>
  )
}
