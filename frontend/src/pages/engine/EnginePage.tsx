import { clsx } from 'clsx'
import { Copy } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate, useParams } from 'react-router-dom'
import { useAgentGraph, useAgentRun, useAgentRuns, useDecisionChain, useSimState } from '@/shared/api/hooks'
import { tEnum } from '@/shared/i18n'
import { fmtDateTime, fmtMs } from '@/shared/lib/format'
import { Badge, Empty, ErrorBox, Json, SkeletonRows, Tabs } from '@/shared/ui'
import { useWs } from '@/shared/ws/client'
import { LogPanel } from '@/widgets/LogPanel'
import { BenchTab } from './BenchTab'
import { GraphView } from './GraphView'
import { QualityTab } from './QualityTab'

type Tab = 'steps' | 'graph' | 'chain' | 'live' | 'quality' | 'bench'

/** Экран 3 «Под капотом» (ТЗ 12.2): список прогонов, шаги с промптами, граф, цепочка решений, живые события WS. */
export function EnginePage() {
  const { t } = useTranslation()
  const { runId: runStr } = useParams()
  const nav = useNavigate()
  const runId = runStr ? Number(runStr) : null
  const live = useWs((s) => s.sim)
  const simQ = useSimState()
  const simRunId = (live ?? simQ.data)?.current_run_id ?? undefined
  const [onlyCurrent, setOnlyCurrent] = useState(true)
  const runs = useAgentRuns({ run_id: onlyCurrent ? simRunId : undefined, limit: 100 })
  const [tab, setTab] = useState<Tab>('steps')
  const items = runs.data?.items ?? []

  return (
    <div className="flex h-full">
      <aside className="flex w-80 shrink-0 flex-col border-r border-line">
        <div className="flex h-10 shrink-0 items-center gap-2 border-b border-line px-3 text-xs">
          <span className="font-semibold uppercase tracking-wide text-muted">{t('engine.runs')}</span>
          <label className="ml-auto flex items-center gap-1 text-muted">
            <input type="checkbox" checked={onlyCurrent} onChange={(e) => setOnlyCurrent(e.target.checked)} /> {t('common.runId', { id: simRunId ?? '—' })}
          </label>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto">
          {runs.isPending && <SkeletonRows />}
          {runs.isError && <ErrorBox error={runs.error} />}
          {runs.data && items.length === 0 && <Empty title={t('common.empty')} />}
          <ul className="divide-y divide-line">
            {items.map((r) => (
              <li key={r.id}>
                <button
                  onClick={() => nav(`/engine/${r.id}`)}
                  className={clsx('block w-full px-3 py-2 text-left hover:bg-raised', r.id === runId && 'bg-brand-soft/50')}
                >
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-xs">#{r.id}</span>
                    <Badge tone={r.outcome === 'completed' ? 'ok' : r.outcome === 'awaiting_human' ? 'warn' : r.outcome === 'failed' ? 'danger' : 'info'}>
                      {tEnum('engine.outcome', r.outcome ?? 'running')}
                    </Badge>
                    {r.needed_human && <Badge tone="warn">HITL</Badge>}
                    <span className="ml-auto num text-[11px] text-muted">{fmtMs(r.total_latency_ms)}</span>
                  </div>
                  <div className="mt-0.5 flex items-center gap-2 text-[11px] text-muted">
                    <span>SIG-{String(r.signal_id ?? 0).padStart(6, '0')}</span>
                    <span>{r.llm_profile_code}</span>
                    <span className="num">{r.total_tokens} ток.</span>
                    <span className="ml-auto num font-mono">{fmtDateTime(r.started_at).slice(6)}</span>
                  </div>
                </button>
              </li>
            ))}
          </ul>
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <Tabs
          value={tab}
          onChange={setTab}
          items={[
            { id: 'steps', label: t('engine.steps') },
            { id: 'graph', label: t('engine.graph') },
            { id: 'chain', label: t('engine.chain') },
            { id: 'live', label: t('engine.live') },
            { id: 'quality', label: t('engine.quality') },
            { id: 'bench', label: t('engine.bench') },
          ]}
        />
        <div className="min-h-0 flex-1 overflow-y-auto">
          {tab === 'steps' && <LogPanel runId={runId} full />}
          {tab === 'graph' && <GraphTab runId={runId} />}
          {tab === 'chain' && <ChainTab runId={runId} />}
          {tab === 'live' && <LiveTab />}
          {tab === 'quality' && <QualityTab />}
          {tab === 'bench' && <BenchTab />}
        </div>
      </div>
    </div>
  )
}

function GraphTab({ runId }: { runId: number | null }) {
  const { t } = useTranslation()
  const g = useAgentGraph()
  const run = useAgentRun(runId)
  const visited = useMemo(() => new Set((run.data?.steps ?? []).map((s) => s.node ?? '')), [run.data])
  if (g.isPending) return <SkeletonRows n={2} />
  if (g.isError) return <ErrorBox error={g.error} />
  return (
    <div className="space-y-3 p-4">
      <div className="text-xs text-muted">
        {t('engine.graph')} · {g.data?.version}
        {runId ? ` · ${t('common.runId', { id: runId })}` : ''}
      </div>
      <div className="card p-3">
        <GraphView graph={g.data!} visited={visited} current={run.data?.current_node ?? null} outcome={run.data?.outcome ?? null} />
      </div>
      {!runId && <Empty title={t('engine.selectRun')} />}
    </div>
  )
}

function ChainTab({ runId }: { runId: number | null }) {
  const { t } = useTranslation()
  const [fmt, setFmt] = useState<'md' | 'json'>('md')
  const q = useDecisionChain(runId, fmt)
  const [copied, setCopied] = useState(false)
  if (runId === null) return <Empty title={t('engine.selectRun')} />
  if (q.isPending) return <SkeletonRows n={3} />
  if (q.isError) return <ErrorBox error={q.error} />
  const copy = () => {
    void navigator.clipboard.writeText(typeof q.data === 'string' ? q.data : JSON.stringify(q.data, null, 2)).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1200)
    })
  }
  return (
    <div className="space-y-2 p-4">
      <div className="flex items-center gap-2">
        <div className="flex rounded-lg border border-line p-0.5">
          {(['md', 'json'] as const).map((f) => (
            <button key={f} className={clsx('h-6 rounded-md px-2 text-xs', fmt === f ? 'bg-raised font-medium' : 'text-muted')} onClick={() => setFmt(f)}>
              {f}
            </button>
          ))}
        </div>
        <button className="btn btn-sm ml-auto" onClick={copy}>
          <Copy size={12} /> {copied ? t('common.copied') : t('common.copy')}
        </button>
      </div>
      {typeof q.data === 'string' ? <pre className="card whitespace-pre-wrap p-4 font-mono text-xs leading-relaxed">{q.data}</pre> : <Json value={q.data} />}
    </div>
  )
}

function LiveTab() {
  const events = useWs((s) => s.events)
  const { t } = useTranslation()
  if (!events.length) return <Empty title={t('common.empty')} hint="События агента, сигналов и инцидентов появятся здесь по WebSocket." />
  return (
    <ul className="divide-y divide-line font-mono text-[11.5px]">
      {events.map((e) => (
        <li key={e.seq} className="flex gap-2 px-3 py-1.5">
          <span className="num shrink-0 text-faint">{e.ts.slice(11, 19)}</span>
          <Badge tone={e.topic === 'agent' ? 'info' : e.topic === 'hitl' ? 'warn' : e.topic === 'incidents' ? 'brand' : 'neutral'}>{e.topic}</Badge>
          <span className="shrink-0 text-muted">{e.type}</span>
          <span className="min-w-0 flex-1 truncate">{JSON.stringify(e.data)}</span>
        </li>
      ))}
    </ul>
  )
}
