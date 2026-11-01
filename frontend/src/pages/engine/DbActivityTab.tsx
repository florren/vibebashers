import { useEffect, useRef, useState } from 'react'
import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { api, type Schemas } from '@/shared/api/client'
import { useSimRuns, useSimState } from '@/shared/api/hooks'
import { useWs } from '@/shared/ws/client'
import { Badge, Empty, ErrorBox, Json, SkeletonRows } from '@/shared/ui'
import { fmtDateTime } from '@/shared/lib/format'

type Counter = { table: string; rows: number; exact: boolean; last_change_at: string | null }
type Activity = Schemas['DbActivity']
const PAGE_SIZE = 50
function rowRef(row: Record<string, unknown>, index: number): string {
  return String(row.id ?? (row.signal_id != null && row.incident_id != null ? `${row.incident_id}/${row.signal_id}` : row.incident_id ?? index))
}

/** Только серверные audit events; WS инвалидирует снимки, polling восстанавливает пропуски. */
export function DbActivityTab() {
  const { t } = useTranslation()
  const [runId, setRunId] = useState('current')
  const [table, setTable] = useState('')
  const [paused, setPaused] = useState(false)
  const [inspect, setInspect] = useState<{ title: string; value: unknown } | null>(null)
  const sim = useSimState()
  const live = useWs(s => s.sim)
  const wsStatus = useWs(s => s.status)
  const epoch = runId === 'current' ? live?.current_run_id ?? sim.data?.current_run_id ?? null : null
  const runs = useSimRuns()
  const options = { enabled: !paused, refetchInterval: paused ? false as const : 5000 }
  const counters = useQuery({ queryKey: ['db', 'tables', runId, epoch], queryFn: () => api<Counter[]>('/api/engine/db/tables', { query: { run_id: runId } }), ...options })
  const activity = useInfiniteQuery({
    queryKey: ['db', 'activity', runId, epoch, table], initialPageParam: null as string | null,
    queryFn: ({ pageParam }) => api<Activity[]>('/api/engine/db/activity', { query: { run_id: runId, table: table || undefined, limit: PAGE_SIZE, cursor: pageParam } }),
    getNextPageParam: (last: Activity[]) => last.length === PAGE_SIZE ? String(last.at(-1)?.id) : undefined,
    ...options,
  })
  const rowTable = table || 'signals'
  const rows = useQuery({ queryKey: ['db', 'rows', runId, epoch, rowTable], queryFn: () => api<Record<string, unknown>[]>(`/api/engine/db/tables/${rowTable}/rows`, { query: { run_id: runId, limit: 50 } }), ...options })
  const previous = useRef<Record<string, number>>({})
  const [deltas, setDeltas] = useState<Record<string, number>>({})
  useEffect(() => {
    const next: Record<string, number> = {}
    const changes: Record<string, number> = {}
    for (const item of counters.data ?? []) {
      next[item.table] = item.rows
      const before = previous.current[item.table]
      if (before != null) changes[item.table] = item.rows - before
    }
    previous.current = next
    setDeltas(changes)
  }, [counters.data])
  useEffect(() => { previous.current = {}; setDeltas({}); setInspect(null) }, [runId, epoch])
  useEffect(() => { setInspect(null) }, [table])
  const events = [...new Map((activity.data?.pages.flat() ?? []).map(item => [item.id, item])).values()]
  const refresh = () => { void counters.refetch(); void activity.refetch(); void rows.refetch() }
  return <div className="relative space-y-4 p-4" data-testid="db-activity">
    <div className="flex flex-wrap items-end gap-3">
      <div className="mr-auto"><h1 className="text-lg font-semibold">{t('db.title')}</h1><p className="text-xs text-muted">{t('db.readonly')}</p></div>
      <label className="grid gap-1 text-xs">{t('db.scope')}<select className="input" aria-label={t('db.scope')} value={runId} onChange={e => setRunId(e.target.value)}><option value="current">{t('db.current')}</option><option value="all">{t('db.all')}</option>{(runs.data?.items ?? []).map(run => <option key={run.id} value={String(run.id)}>#{run.id} · {run.label}</option>)}</select></label>
      <label className="grid gap-1 text-xs">{t('db.table')}<select className="input" aria-label={t('db.table')} value={table} onChange={e => setTable(e.target.value)}><option value="">{t('db.allTables')}</option>{counters.data?.map(item => <option key={item.table} value={item.table}>{item.table}</option>)}</select></label>
      <button className="btn btn-sm" aria-pressed={paused} onClick={() => setPaused(!paused)}>{t(paused ? 'db.resume' : 'db.pause')}</button>
      <button className="btn btn-sm" onClick={refresh}>{t('db.refresh')}</button>
    </div>
    <div className="flex flex-wrap items-center gap-2 text-xs text-muted" role="status"><Badge tone={paused ? 'warn' : wsStatus === 'open' ? 'ok' : 'neutral'}>{t(paused ? 'db.paused' : wsStatus === 'open' ? 'db.live' : 'db.polling')}</Badge>{t('db.legacy')} · {t('db.limit')}</div>
    {runs.isError && <ErrorBox error={runs.error} />}
    {counters.isPending && <SkeletonRows n={2} />}{counters.isError && <ErrorBox error={counters.error} />}
    <div className="grid grid-cols-2 gap-2 md:grid-cols-4 xl:grid-cols-6" aria-label={t('db.counters')}>
      {counters.data?.map(item => <button key={item.table} onClick={() => setTable(item.table)} className={`card min-w-0 p-3 text-left ${table === item.table ? 'ring-1 ring-brand' : ''}`}>
        <div className="truncate font-mono text-[11px]" title={item.table}>{item.table}</div><div className="mt-1 flex items-baseline gap-2"><strong className="num text-xl">{item.exact ? '' : '≈'}{item.rows.toLocaleString()}</strong>{deltas[item.table] !== undefined && deltas[item.table] !== 0 && <span className="num text-xs text-brand" aria-label={t('db.delta')}>{(deltas[item.table] ?? 0) > 0 ? '+' : ''}{deltas[item.table]}</span>}</div><div className="text-[10px] text-muted">{t(item.exact ? 'db.exact' : 'db.estimated')}</div>{item.last_change_at && <div className="mt-1 truncate text-[10px] text-faint">{fmtDateTime(item.last_change_at)}</div>}
      </button>)}
    </div>
    <div className="grid min-w-0 gap-4 xl:grid-cols-2">
      <section className="card min-w-0 p-3"><h2 className="mb-2 font-semibold">{t('db.activity')}</h2>
        {activity.isPending && <SkeletonRows n={4} />}{activity.isError && <ErrorBox error={activity.error} />}{activity.data && events.length === 0 && <Empty title={t('db.emptyActivity')} />}
        <ol className="max-h-96 divide-y divide-line overflow-y-auto" aria-label={t('db.activity')}>{events.map(item => <li key={item.id}><button className="flex w-full flex-wrap items-center gap-2 py-2 text-left text-xs hover:bg-raised" onClick={() => setInspect({ title: `${item.table_name} ${item.op} #${item.pk}`, value: item })}><span className="font-mono text-faint">#{item.id}</span><Badge tone={item.op === 'INSERT' ? 'ok' : item.op === 'DELETE' ? 'danger' : 'info'}>{item.op}</Badge><span className="min-w-0 break-all font-mono">{item.table_name}</span><span className="font-mono text-muted">{item.pk}</span><span className="ml-auto text-muted">{item.run_id != null ? t('db.run', { id: item.run_id }) : t('db.unknownRun')}</span><time className="w-full text-[10px] text-faint">{fmtDateTime(item.ts)}</time></button></li>)}</ol>
        {activity.hasNextPage && <button className="btn btn-sm mt-2" disabled={activity.isFetchingNextPage} onClick={() => void activity.fetchNextPage()}>{t('db.older')}</button>}
      </section>
      <section className="card min-w-0 p-3"><h2 className="mb-2 font-semibold">{t('db.rows')} · <span className="font-mono text-sm">{rowTable}</span></h2><p className="mb-2 text-xs text-muted">{t('db.masked')}</p>
        {rows.isPending && <SkeletonRows n={4} />}{rows.isError && <ErrorBox error={rows.error} />}{rows.data?.length === 0 && <Empty title={t('db.emptyRows')} />}
        <ul className="max-h-96 divide-y divide-line overflow-y-auto" aria-label={t('db.rows')}>{rows.data?.map((row, index) => <li key={rowRef(row, index)}><button className="flex w-full min-w-0 items-center gap-2 py-2 text-left text-xs hover:bg-raised" onClick={() => setInspect({ title: `${rowTable} #${rowRef(row, index)}`, value: row })}><span className="shrink-0 font-mono">#{rowRef(row, index)}</span><span className="truncate text-muted">{String(row.public_id ?? row.node ?? row.status ?? row.to_status ?? row.state ?? '—')}</span><span className="ml-auto shrink-0 text-brand">{t('db.inspect')}</span></button></li>)}</ul>
      </section>
    </div>
    {inspect && <section className="card min-w-0 p-3" aria-label={t('db.inspector')}><div className="mb-2 flex items-center gap-2"><h2 className="min-w-0 break-all font-mono text-sm">{inspect.title}</h2><button className="btn btn-sm ml-auto" onClick={() => setInspect(null)}>{t('common.close')}</button></div><Json value={inspect.value} /></section>}
  </div>
}
