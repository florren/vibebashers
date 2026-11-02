import { useQuery } from '@tanstack/react-query'
import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { ROUTES } from '@/shared/routes'
import { getTraceRelations, type Trace } from '@/shared/api/trace'
import { buildGraph, NODE_HEIGHT, NODE_WIDTH, nodeInViewport, type GraphNode, type NodeFamily } from './graphModel'

const icons: Record<NodeFamily, string> = { signal: '◉', incident: '◆', client: '◎', action: '⚙', money: '₽', message: '✉' }

function Shape({ family }: { family: NodeFamily }) {
  if (family === 'client') return <ellipse className="trace-node-shape" cx={108} cy={38} rx={108} ry={38} />
  if (family === 'incident') return <polygon className="trace-node-shape" points="16,0 200,0 216,38 200,76 16,76 0,38" />
  if (family === 'money') return <polygon className="trace-node-shape" points="12,0 204,0 216,12 216,64 204,76 12,76 0,64 0,12" />
  if (family === 'message') return <path className="trace-node-shape" d="M8 0 H208 Q216 0 216 8 V60 Q216 68 208 68 H30 L16 76 V68 H8 Q0 68 0 60 V8 Q0 0 8 0Z" />
  return <rect className="trace-node-shape" width={NODE_WIDTH} height={NODE_HEIGHT} rx={family === 'signal' ? 22 : 4} />
}

export function GraphView({ trace, scope, visited, onVisit }: { trace: Trace; scope: string; visited: Set<string>; onVisit: (id: string) => void }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const marker = useId().replace(/:/g, '')
  const viewport = useRef<HTMLDivElement>(null)
  const buttons = useRef(new Map<string, SVGGElement>())
  const [zoom, setZoom] = useState(1)
  const [view, setView] = useState({ left: 0, top: 0, width: 800, height: 420 })
  const [fan, setFan] = useState<number | null>(null)
  const [cursors, setCursors] = useState<(string | undefined)[]>([undefined])
  const group = fan == null ? undefined : trace.groups[fan]
  const anchor = group?.anchor
  const fanQuery = useQuery({
    queryKey: ['trace', 'relations', anchor?.kind, anchor?.ref, group?.phase, group?.kind, scope, cursors.at(-1)],
    queryFn: () => getTraceRelations(anchor!.kind, anchor!.ref, {
      direction: group!.phase!, event_kind: group!.kind as 'signal_created' | 'notification',
      run_id: scope, limit: 50, ...(cursors.at(-1) ? { cursor: cursors.at(-1)! } : {}),
    }),
    enabled: !!anchor && !!group?.phase && ['signal_created', 'notification'].includes(group.kind),
    // Only the current fan page is retained: opening all N must not grow the DOM/cache to N.
    gcTime: 0,
  })
  const model = useMemo(() => buildGraph(trace, fanQuery.data), [trace, fanQuery.data])
  const nodes = useMemo(() => new Map(model.nodes.map((node) => [node.id, node])), [model.nodes])
  const selectedId = nodes.has(params.get('focus') ?? '') ? params.get('focus')! : model.subjectId
  const selected = nodes.get(selectedId)!
  const drawn = model.nodes.filter((node) => node.id === selectedId || nodeInViewport(node, view, zoom))
  const drawnIds = new Set(drawn.map((node) => node.id))
  const visibleEdges = model.edges.filter((edge) => drawnIds.has(edge.from) || drawnIds.has(edge.to))

  useEffect(() => {
    const element = viewport.current
    if (!element) return
    const measure = () => setView({ left: element.scrollLeft, top: element.scrollTop, width: element.clientWidth, height: element.clientHeight })
    const observer = new ResizeObserver(measure)
    observer.observe(element)
    measure()
    return () => observer.disconnect()
  }, [])
  useEffect(() => { setFan(null); setCursors([undefined]) }, [trace.subject.kind, trace.subject.ref, scope])
  useEffect(() => {
    // A narrow viewport otherwise opens on an empty BEFORE column. Pan to the
    // selected real node without taking keyboard focus from the surrounding page.
    const element = viewport.current
    const node = nodes.get(selectedId)
    if (!element || !node) return
    element.scrollTo({ left: Math.max(0, (node.x + NODE_WIDTH / 2) * zoom - element.clientWidth / 2), top: Math.max(0, (node.y + NODE_HEIGHT / 2) * zoom - element.clientHeight / 2) })
    setView({ left: element.scrollLeft, top: element.scrollTop, width: element.clientWidth, height: element.clientHeight })
  }, [nodes, selectedId, zoom])

  const focusNode = (node: GraphNode, keyboard = false) => {
    const next = new URLSearchParams(params)
    next.set('focus', node.id)
    setParams(next, { replace: true })
    const el = viewport.current
    if (el) {
      el.scrollTo({ left: Math.max(0, (node.x + NODE_WIDTH / 2) * zoom - el.clientWidth / 2), top: Math.max(0, (node.y + NODE_HEIGHT / 2) * zoom - el.clientHeight / 2) })
      setView({ left: el.scrollLeft, top: el.scrollTop, width: el.clientWidth, height: el.clientHeight })
    }
    if (keyboard) requestAnimationFrame(() => buttons.current.get(node.id)?.focus({ preventScroll: true }))
  }
  const center = (node: GraphNode) => {
    onVisit(node.id)
    focusNode(node)
    const href = node.event?.links.trace
    if (href?.startsWith('/trace/') && node.id !== model.subjectId) {
      const next = new URLSearchParams(params)
      next.set('mode', 'graph'); next.set('run_id', scope); next.set('focus', node.id)
      navigate(`${href.split('?')[0]}?${next}`)
    }
  }
  const keyboard = (event: KeyboardEvent<SVGGElement>, node: GraphNode) => {
    const index = model.nodes.findIndex((item) => item.id === node.id)
    const keys = ['ArrowRight', 'ArrowDown', 'ArrowLeft', 'ArrowUp', '[', ']', 'Home', 'End', 'Enter', ' ']
    if (!keys.includes(event.key)) return
    event.preventDefault()
    if (event.key === 'Enter' || event.key === ' ') { center(node); return }
    const target = event.key === 'Home' ? nodes.get(model.subjectId) : event.key === 'End' ? nodes.get(model.terminalId ?? '') :
      model.nodes[(index + (['ArrowLeft', 'ArrowUp', '['].includes(event.key) ? -1 : 1) + model.nodes.length) % model.nodes.length]
    if (target) focusNode(target, true)
  }
  const transition = selected.event?.links
  return (
    <div className="trace-graph" data-testid="trace-graph">
      <section className="trace-graph-main" aria-label={t('traceGraph.graph')}>
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <button className="btn" onClick={() => setZoom((value) => Math.max(.5, value - .25))} disabled={zoom <= .5} aria-label={t('traceGraph.zoomOut')}>−</button>
          <output aria-label={t('traceGraph.zoom')}>{Math.round(zoom * 100)}%</output>
          <button className="btn" onClick={() => setZoom((value) => Math.min(2, value + .25))} disabled={zoom >= 2} aria-label={t('traceGraph.zoomIn')}>+</button>
          <button className="btn" onClick={() => focusNode(nodes.get(model.subjectId)!, true)}>{t('traceGraph.toCenter')}</button>
          <span className="text-xs text-muted">{t('traceGraph.keyboard')}</span>
        </div>
        {model.unresolved && <p role="status">{t('traceGraph.unresolved')}</p>}
        {model.hiddenEdges > 0 && <p role="status">{t('traceGraph.hiddenEdges')}</p>}
        <div ref={viewport} className="trace-graph-viewport" onScroll={(event) => {
          const el = event.currentTarget
          setView({ left: el.scrollLeft, top: el.scrollTop, width: el.clientWidth, height: el.clientHeight })
        }}>
          <svg width={model.width * zoom} height={model.height * zoom} viewBox={`0 0 ${model.width} ${model.height}`}
            role="group" aria-label={t('traceGraph.graph')} data-node-count={model.nodes.length}>
            <defs><clipPath id={`${marker}-text`}><rect x={16} y={8} width={NODE_WIDTH - 32} height={NODE_HEIGHT - 12} /></clipPath><marker id={marker} viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0 L8 4 L0 8Z" fill="currentColor" /></marker></defs>
            {(['before', 'subject', 'after'] as const).map((phase, i) => <text key={phase} x={32 + i * 340} y={24} className="fill-ink text-sm font-semibold">{t(`traceUi.${phase}`)}</text>)}
            {visibleEdges.map((edge) => {
              const a = nodes.get(edge.from)!, b = nodes.get(edge.to)!
              const sx = a.x + NODE_WIDTH, sy = a.y + NODE_HEIGHT / 2, tx = b.x, ty = b.y + NODE_HEIGHT / 2
              const highlighted = model.pathEdges.has(`${edge.from}\0${edge.to}`)
              return <g key={`${edge.from}:${edge.to}:${edge.relation_ru}`} className={highlighted ? 'trace-graph-edge on-path' : 'trace-graph-edge'}>
                <path d={`M${sx} ${sy} C${(sx + tx) / 2} ${sy} ${(sx + tx) / 2} ${ty} ${tx} ${ty}`} fill="none" markerEnd={`url(#${marker})`} />
                <text x={(sx + tx) / 2} y={(sy + ty) / 2 - 7} textAnchor="middle" className="fill-muted text-[10px]">{edge.relation_ru.slice(0, 25)}<title>{edge.relation_ru}</title></text>
              </g>
            })}
            {drawn.map((node) => <g key={node.id} ref={(element) => { if (element) buttons.current.set(node.id, element); else buttons.current.delete(node.id) }}
              transform={`translate(${node.x},${node.y})`} role="button" tabIndex={selectedId === node.id ? 0 : -1}
              aria-label={`${t(`traceGraph.family.${node.family}`)}: ${node.title} ${node.ref}`}
              aria-pressed={selectedId === node.id} data-node-id={node.id}
              className={`trace-graph-node ${selectedId === node.id ? 'selected' : ''} ${visited.has(node.id) ? 'visited' : ''} ${model.path.has(node.id) ? 'on-path' : ''}`}
              onFocus={() => { if (selectedId !== node.id) focusNode(node) }} onKeyDown={(event) => keyboard(event, node)} onClick={() => center(node)}>
              <title>{node.title} · {node.ref}</title><Shape family={node.family} />
              <g clipPath={`url(#${marker}-text)`}><text x={18} y={27} className="fill-ink text-sm"><tspan>{icons[node.family]} </tspan>{node.title.slice(0, 20)}</text>
              <text x={18} y={49} className="fill-muted font-mono text-[11px]">{node.ref.slice(0, 25)}</text>
              <text x={18} y={65} className="fill-muted text-[10px]">{node.event?.badges.llm_source ?? t(`traceGraph.family.${node.family}`)}{visited.has(node.id) ? ' ✓' : ''}{node.id === model.terminalId ? ' ⚑' : ''}</text></g>
            </g>)}
          </svg>
        </div>
        <div className="trace-graph-footer">
          <svg className="trace-minimap" viewBox={`0 0 ${model.width} ${model.height}`} preserveAspectRatio="none" role="img" aria-label={t('traceGraph.minimap')}>
            {model.nodes.map((node) => <rect key={node.id} x={node.x} y={node.y} width={NODE_WIDTH} height={NODE_HEIGHT} className={node.id === selectedId ? 'fill-brand' : 'fill-muted'} />)}
            <rect x={view.left / zoom} y={view.top / zoom} width={Math.min(view.width / zoom, model.width)} height={Math.min(view.height / zoom, model.height)} fill="none" className="stroke-brand" strokeWidth={10} />
          </svg>
          <div><p>⚑ {trace.terminal.outcome_ru}</p>{!model.path.size && <p className="text-xs text-muted">{t('traceGraph.noPath')}</p>}
            <p className="text-xs text-muted">{t('traceGraph.rendered', { visible: drawn.length, total: model.nodes.length })}</p>
          </div>
        </div>
        {trace.groups.length > 0 && <section aria-label={t('traceGraph.fans')} className="mt-3">
          <h3 className="font-semibold">{t('traceGraph.fans')}</h3>
          <div className="flex flex-wrap gap-2">{trace.groups.map((item, index) => <button key={index} className="btn" aria-pressed={fan === index}
            disabled={!item.anchor || !item.phase || !['signal_created', 'notification'].includes(item.kind)}
            onClick={() => { setFan(fan === index ? null : index); setCursors([undefined]) }}>
            {t(`traceUi.eventKind.${item.kind}`, { defaultValue: item.kind })} · {item.count}{item.anchor ? ` · ${item.anchor.ref}` : ''}
          </button>)}</div>
          {trace.groups.some((item) => !item.anchor || !item.phase) && <p>{t('traceGraph.legacyFan')}</p>}
          {fan != null && <div className="my-2 rounded border border-line p-3">
            {anchor && <Link className="btn mb-2" to={`${ROUTES.traceObject(anchor.kind, anchor.ref)}?${new URLSearchParams({ mode: 'graph', run_id: scope })}`}>{t('traceGraph.groupParent')} · {anchor.ref}</Link>}
            {fanQuery.isFetching && <p role="status">{t('traceUi.loading')}</p>}
            {fanQuery.isError && <p role="alert">{t('traceGraph.fanError')} <button className="btn" onClick={() => { setCursors([undefined]); void fanQuery.refetch() }}>{t('traceUi.retry')}</button></p>}
            {fanQuery.data && <><p role="status">{t('traceGraph.page', { start: fanQuery.data.items.length ? (cursors.length - 1) * 50 + 1 : 0, end: (cursors.length - 1) * 50 + fanQuery.data.items.length, total: fanQuery.data.total })}</p>
              <div className="my-2 flex gap-2"><button className="btn" disabled={cursors.length === 1 || fanQuery.isFetching} onClick={() => setCursors((value) => value.slice(0, -1))}>{t('traceGraph.previous')}</button>
                <button className="btn" disabled={!fanQuery.data.next_cursor || fanQuery.isFetching} onClick={() => setCursors((value) => [...value, fanQuery.data!.next_cursor!])}>{t('traceGraph.next')}</button></div>
              <ul className="trace-fan-list">{fanQuery.data.items.map((item) => <li key={item.id}><button className="btn" onClick={() => focusNode(nodes.get(item.id)!, true)}>{item.object_ref?.ref ?? item.title_ru}</button></li>)}</ul>
            </>}
          </div>}
        </section>}
        {trace.pending.map((item, index) => <p className="mt-2 rounded border border-dashed border-line p-2" key={index}>◷ {item.kind_ru} {item.due_sim ?? ''}</p>)}
      </section>
      <aside className="trace-graph-panel" aria-label={t('traceGraph.inspector')}>
        <h2 className="mb-3 font-semibold">{selected.title}</h2>
        {(['summary', 'relations', 'data', 'transition'] as const).map((section) => <details key={`${selectedId}:${section}`} open={section === 'summary'} className="trace-graph-accordion">
          <summary>{t(`traceGraph.${section}`)}</summary><div className="trace-graph-accordion-body"><div>
            {section === 'summary' && <><p>{selected.event?.brief_ru ?? trace.subject.title_ru}</p><p className="font-mono text-xs">{selected.ref}</p>{selected.event?.badges.llm_source && <p>{selected.event.badges.llm_source}</p>}{selected.event?.key_facts.map((fact, index) => <p key={index}>{fact.label_ru}: {fact.value_ru}</p>)}</>}
            {section === 'relations' && <ul>{model.edges.filter((edge) => edge.from === selectedId || edge.to === selectedId).map((edge) => {
              const other = nodes.get(edge.from === selectedId ? edge.to : edge.from)!
              return <li key={`${edge.from}:${edge.to}`}><button className="btn" onClick={() => focusNode(other, true)}>{edge.relation_ru} · {other.ref || other.title}</button></li>
            })}</ul>}
            {section === 'data' && <pre className="overflow-auto whitespace-pre-wrap break-all text-xs">{JSON.stringify(selected.event ?? trace.subject, null, 2)}</pre>}
            {section === 'transition' && <div className="flex flex-wrap gap-2">
              {selected.event?.links.trace?.startsWith('/trace/') && <button className="btn" onClick={() => center(selected)}>{t('traceUi.center')}</button>}
              {transition?.engine_step?.startsWith('/engine/') && <Link className="btn" to={transition.engine_step}>{t('traceUi.engine')}</Link>}
              {transition?.journey?.startsWith('/journey/') && <Link className="btn" to={transition.journey}>{t('traceGraph.journey')}</Link>}
              {!transition?.trace && !transition?.engine_step && !transition?.journey && <p>{t('traceGraph.noTransition')}</p>}
            </div>}
          </div></div>
        </details>)}
      </aside>
    </div>
  )
}
