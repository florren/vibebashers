import { useState, type ReactNode } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { api, type Schemas, type DecisionChain } from '@/shared/api/client'
import { useSimRuns } from '@/shared/api/hooks'
import { useWs } from '@/shared/ws/client'
import { useUiTheme } from '@/shared/theming/store'
import { useViewPreset } from '@/shared/layout/preset'
import { resolveAttention } from '@/shared/theming/attention'
import { useNight } from '@/shared/theming/night'
import { NightDecoration } from '@/shared/theming/NightDigest'
import { Badge, Empty, ErrorBox, Skeleton } from '@/shared/ui'
import { tEnum } from '@/shared/i18n'
import { formatExactRub } from '@/shared/lib/exactMoney'
import { fmtSimMoscow } from '@/shared/lib/format'
import { maskBusinessText } from '@/shared/lib/privacy'
import { ROUTES } from '@/shared/routes'
import { SourcePlatformBadge } from '@/shared/components/SourcePlatformBadge'
import { useOverview, useCxIndex, useOverviewSignals } from './api'
import { customerWindow } from './model'
import { OverviewChart } from './OverviewChart'
import { SignalProjection } from './SignalProjection'

function Block({ id, title, to, enabled, children }: { id: string; title: string; to: string; enabled: boolean; children: ReactNode }) {
  const { t } = useTranslation()
  return <section data-block={`overview-${id}`} className="card min-w-0 space-y-3 p-4"><div className="flex flex-wrap items-center justify-between gap-2"><h2 className="font-semibold">{title}</h2>{enabled ? <Link className="text-sm text-brand underline" to={to}>{t('overviewUi.openFull')}</Link> : <span aria-disabled="true" className="text-sm text-muted">{t('overviewUi.openFull')}</span>}</div>{children}</section>
}

export function OverviewPage() {
  const { t, i18n } = useTranslation()
  const [params, setParams] = useSearchParams(), requested = params.get('run_id') ?? 'current'
  const data = useOverview(requested), runs = useSimRuns()
  const [selection, setSelection] = useState<{ scope: string; id: number } | null>(null)
  // Current разрешается один раз для дочерних запросов; NULL не превращается в global.
  const run = data.data && !data.isError ? data.data.scope.all_runs ? 'all' : data.data.scope.resolved_run_id != null ? String(data.data.scope.resolved_run_id) : null : null
  const cx = useCxIndex(run), since = cx.data?.window.starts_sim
  const signals = useOverviewSignals(run, since)
  const night = useNight(), nightSignals = useOverviewSignals(night ? run : null, since, true)
  const agents = useQuery({ queryKey: ['agent', 'overview', run], queryFn: ({ signal }) => api<Schemas['AgentRunList']>('/api/agent/runs', { query: { run_id: run, kind: 'agent', limit: 10 }, signal }), enabled: run !== null, refetchInterval: 8000 })
  const selected = agents.data?.items?.find(row => row.id === (selection?.scope === run ? selection.id : undefined)) ?? agents.data?.items?.[0]
  const chain = useQuery({ queryKey: ['agent', 'chain', selected?.id, run], queryFn: ({ signal }) => api<DecisionChain>(`/api/agent/runs/${selected?.id}/decision-chain`, { query: { format: 'json' }, signal }), enabled: run !== null && selected?.id !== undefined, refetchInterval: 8000 })
  const queue = useQuery({ queryKey: ['hitl', 'overview', run], queryFn: ({ signal }) => api<Schemas['HitlList']>('/api/hitl/queue', { query: { run_id: run, limit: 3, include_decided: false }, signal }), enabled: run !== null, refetchInterval: 5000 })
  const ws = useWs(s => s.status), role = useViewPreset(s => s.role)
  const attention = useUiTheme(s => s.attention), pack = useUiTheme(s => s.theme_pack)
  const mode = resolveAttention(attention, pack, '/overview', role)
  const scopeQuery = `run_id=${encodeURIComponent(run ?? requested)}`
  const full = (tab: string) => `/workspace?tab=${tab}&${scopeQuery}`
  const source = data.isError || data.data?.scope.current_missing ? undefined : data.data
  const rows = cx.data ? customerWindow(signals.data?.items ?? [], cx.data.window.starts_sim, cx.data.window.ends_sim) : []
  const highRows = cx.data ? customerWindow(nightSignals.data?.items ?? [], cx.data.window.starts_sim, cx.data.window.ends_sim) : []
  const number = (value: number | null | undefined, suffix = '') => value == null ? '—' : `${new Intl.NumberFormat(i18n.language, { maximumFractionDigits: 1 }).format(value)}${suffix}`
  const money = formatExactRub(source?.kpi.saved_rub_exact ?? null, i18n.language)
  const index = cx.isError ? undefined : cx.data
  const online = ws === 'open' && Boolean(source) && !cx.isError
  const readable = (loading: boolean, error: unknown, children: ReactNode) => error ? <ErrorBox error={error} /> : loading ? <Skeleton className="h-32" /> : children
  const signalRef = selected?.signal_id != null ? String(selected.signal_id) : null
  return <div className="h-full min-w-0 overflow-y-auto p-3 sm:p-5" data-overview data-attention={mode}>
    {night && <NightDecoration />}
    <div className="relative mx-auto max-w-[1600px] space-y-4">
      <header className="flex flex-wrap items-end justify-between gap-3"><div><h1 className="text-2xl font-semibold">{t('overviewUi.title')}</h1><p className="mt-1 text-sm text-muted">{t('overviewUi.subtitle')}</p></div><label className="flex min-w-0 max-w-full flex-col gap-1 text-sm sm:flex-row sm:items-center">{t('overviewUi.scope')}<select className="input min-w-0 max-w-full sm:ml-2" value={requested} onChange={event => { const next = new URLSearchParams(params); next.set('run_id', event.target.value); setParams(next); setSelection(null) }}><option value="current">{t('overviewUi.current')}</option><option value="all">{t('overviewUi.all')}</option>{!['current', 'all'].includes(requested) && !runs.data?.items?.some(row => String(row.id) === requested) && <option value={requested}>{/^[1-9][0-9]{0,18}$/.test(requested) ? `#${requested}` : t('overviewUi.invalidScopeShort')}</option>}{runs.data?.items?.map(row => <option key={row.id} value={row.id}>#{row.id} · {row.label}</option>)}</select></label></header>
      <p className="flex flex-wrap items-center gap-2 text-sm" role="status"><span aria-hidden="true" className={`h-2 w-2 rounded-full ${online ? 'bg-ok' : 'bg-warn'}`} />{t(online ? 'overviewUi.connected' : 'overviewUi.connectionPending')}<span className="text-muted">{source ? fmtSimMoscow(source.as_of_sim) : '—'} · {t('overviewUi.mode.' + mode)}</span></p>
      {!data.isError && data.data?.scope.current_missing && <p className="rounded border border-line p-3 text-sm">{t('overviewUi.noCurrent')}</p>}
      <div className="grid min-w-0 gap-4 xl:grid-cols-2">
        <div className="min-w-0 xl:col-span-2"><Block enabled={run !== null} id="kpi" title={t('overviewUi.kpi')} to={full('dashboard')}>
          {readable(data.isPending, data.error, <><dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-6">{[
            ['signalsToday', number(source?.kpi.signals_today)], ['criticalToday', number(source?.kpi.critical_today)], ['autonomous', number(source?.kpi.autonomous_share, '%')], ['response', number(source?.kpi.agent_response_p50_ms, ' ' + t('overviewUi.ms'))], ['sla', number(source?.kpi.sla_risk_incidents)], ['saved', money.compact],
          ].map(([key, value]) => <div key={key}><dt className="text-sm text-muted">{t('overviewUi.' + key)}</dt><dd className="num mt-1 break-words text-2xl font-semibold" title={key === 'saved' ? money.exact : undefined} data-kpi={key}>{value}</dd></div>)}</dl><p className="text-sm text-muted">{t('overviewUi.kpiBasis')}</p>{source && <p className="text-xs text-muted">{t('overviewUi.coverage', { signals: source.coverage.signals_today, criticality: source.coverage.criticality_known_today, runs: source.coverage.agent_runs, outcomes: source.coverage.outcome_known, latency: source.coverage.latency_known, economics: source.coverage.economics_known, incidents: source.coverage.incidents })}</p>}</>)}
        </Block></div>
        <Block enabled={run !== null} id="cx" title={t('overviewUi.tension')} to={full('signals')}>
          {readable(cx.isFetching && !index && run !== null, cx.error, <>
            <Badge>{t('overviewUi.demonstration')}</Badge>
            <div className="flex flex-wrap items-baseline gap-3">
              <strong className="num text-4xl" data-cx-index>{number(index?.index)}</strong>
              <span className="text-sm text-muted">{t('overviewUi.delta', { delta: number(index?.delta_hour) })}</span>
            </div>
            <p className="text-sm text-muted">{t('overviewUi.unknownHint')}</p>
            <SignalProjection rows={rows} run={run} />
            {signals.isError && <ErrorBox error={signals.error} />}
            <p className="text-xs text-muted">{t('overviewUi.sample', { limit: 40, shown: rows.length })}</p>
            <details className="text-sm">
              <summary className="cursor-pointer">{t('overviewUi.components')}</summary>
              {index && <>
                <dl className="mt-2 grid grid-cols-2 gap-2">{Object.entries(index.components).map(([key, component]) => <div className="min-w-0 break-words" key={key}>
                  <dt>{t('overviewUi.component.' + key)}</dt>
                  <dd className="num">{number(component.value)} · {component.known}/{component.total ?? '—'}</dd>
                </div>)}</dl>
                <p className="mt-2 text-muted">{t('overviewUi.slaBasis')}</p>
                <p className="text-muted">{t('overviewUi.previousBasis')}</p>
                <p>{t('overviewUi.weightsSource')}: {t('overviewUi.weights.' + index.weights_source)}</p>
                {index.weights && <p className="num">{Object.entries(index.weights).map(([key, value]) => `${t('overviewUi.component.' + key)}: ${value}`).join(' · ')}</p>}
              </>}
            </details>
          </>)}
        </Block>
        <Block enabled={run !== null} id="channels" title={t('overviewUi.channels')} to={full('signals')}>{index ? <OverviewChart data={index} kind="channels" /> : cx.isError ? <ErrorBox error={cx.error} /> : <Empty title={t('overviewUi.noData')} />}</Block>
        <Block enabled={run !== null} id="flow" title={t('overviewUi.flow')} to={full('signals')}>{index ? <><OverviewChart data={index} kind="flow" /><p className="text-xs text-muted">{t('overviewUi.flowHint')}</p></> : cx.isError ? <ErrorBox error={cx.error} /> : <Empty title={t('overviewUi.noData')} />}</Block>
        <Block enabled={run !== null} id="decision" title={t('overviewUi.decision')} to={`/engine?${scopeQuery}`}>
          {readable(agents.isFetching && !agents.data && run !== null, agents.error, agents.data?.items?.length ? <><label className="block text-sm">{t('overviewUi.agentRun')}<select className="input mt-1 w-full" value={selected?.id ?? ''} onChange={event => setSelection({ scope: run ?? '', id: Number(event.target.value) })}>{agents.data.items.map(row => <option key={row.id} value={row.id}>#{row.id} · {row.outcome ? tEnum('engine.outcome', row.outcome) : t('overviewUi.running')}</option>)}</select></label>{chain.isError ? <ErrorBox error={chain.error} /> : chain.isPending ? <Skeleton className="h-24" /> : <><Badge>{chain.data.llm_source ?? t('overviewUi.unknownMode')}</Badge><ol className="max-h-72 space-y-3 overflow-y-auto">{chain.data.steps.map(step => <li key={step.step} className="border-l-2 border-line pl-3"><span className="font-medium">{step.step}. {tEnum('engine.node', step.node)}</span>{step.tool && <span className="ml-2 font-mono text-xs">{step.tool}</span>}<p className="mt-1 text-sm text-muted">{maskBusinessText(step.why_ru)}</p></li>)}</ol></>}{selected && <div className="flex flex-wrap gap-3"><Link className="btn btn-sm" to={`/engine/${selected.id}?${scopeQuery}`}>{t('overviewUi.openAgent')}</Link>{signalRef && <><Link className="btn btn-sm" to={`${ROUTES.journeyObject(signalRef)}?${scopeQuery}`}>{t('overviewUi.journey')}</Link><Link className="btn btn-sm" to={`${ROUTES.traceObject('signal', signalRef)}?${scopeQuery}`}>{t('overviewUi.trace')}</Link></>}</div>}</> : <Empty title={t('overviewUi.noAgent')} />)}
        </Block>
        <Block enabled={run !== null} id="feed" title={t('overviewUi.feed')} to={full('signals')}>
          {night && <details className="rounded border border-line p-2 text-sm" data-testid="overview-night-digest"><summary>{t('theme.circadian.digest')}</summary>{nightSignals.isError ? <ErrorBox error={nightSignals.error} /> : <ul>{highRows.map(row => <li key={row.id}><Link className="text-brand underline" to={`${ROUTES.traceObject('signal', row.public_id ?? String(row.id))}?${scopeQuery}`}>{row.public_id ?? row.id}</Link></li>)}</ul>}<p className="text-muted">{t('overviewUi.sample', { limit: 10, shown: highRows.length })}</p></details>}
          {readable(signals.isFetching && !signals.data && run !== null, signals.error, rows.length ? <ul className="space-y-3">{rows.slice(0, mode === 'calm' ? 6 : 10).map(row => <li key={row.id} className="flex flex-wrap items-start justify-between gap-2 border-b border-line pb-2"><div><Link className="font-mono text-sm text-brand underline" to={`${ROUTES.traceObject('signal', row.public_id ?? String(row.id))}?${scopeQuery}`}>{row.public_id ?? row.id}</Link><p className="mt-1 text-sm">{tEnum('signal.type', row.signal_type)} · {tEnum('signal.status', row.status)}</p><div className="mt-1 flex flex-wrap gap-2"><Badge>{tEnum('channel', row.channel_code)}</Badge>{row.criticality === 'high' && <Badge tone="danger">{t('overviewUi.critical')}</Badge>}{(row.flags.includes('sarcasm') || row.tone === 'sarcastic') && <Badge>{t('overviewUi.sarcasm')}</Badge>}{row.negativity != null && row.negativity >= 67 && <Badge>{t('overviewUi.highNegativity')}</Badge>}</div><SourcePlatformBadge platform={row.source_platform} /></div><time className="text-xs text-muted">{row.received_sim ? fmtSimMoscow(row.received_sim) : '—'}</time></li>)}</ul> : <Empty title={t('overviewUi.noSignals')} />)}<p className="text-xs text-muted">{t('overviewUi.sample', { limit: 40, shown: rows.length })}</p>
        </Block>
        <Block enabled={run !== null} id="queue" title={t('overviewUi.queue')} to={full('hitl')}>
          {readable(queue.isFetching && !queue.data && run !== null, queue.error, queue.data?.items?.length ? <ul className="space-y-3">{queue.data.items.slice(0, 3).map(item => <li key={item.id} className="border-b border-line pb-3"><Link className="font-mono text-sm text-brand underline" to={full('hitl')}>{item.public_id ?? `#${item.id}`}</Link><p className="mt-1 text-sm">{tEnum('hitl.reason', item.reason)}</p><p className="mt-1 text-xs text-muted">{t('overviewUi.waiting', { minutes: number(item.waiting_minutes) })}</p>{item.signal?.public_id && <Link className="text-sm text-brand underline" to={`${ROUTES.journeyObject(item.signal.public_id)}?${scopeQuery}`}>{t('overviewUi.journey')}</Link>}</li>)}</ul> : <Empty title={t('overviewUi.noQueue')} />)}<p className="text-xs text-muted">{t('overviewUi.firstThree')}</p>
        </Block>
        <Block enabled={run !== null} id="economy" title={t('overviewUi.pressure')} to={`/economics?${scopeQuery}`}>
          <p className="text-3xl font-semibold num" data-money-exact title={money.exact}>{money.compact}</p><p className="break-words text-sm">{money.exact}</p><p className="text-xs text-muted">{t('overviewUi.savedHint')}</p>{source && <><dl className="grid max-h-64 grid-cols-2 gap-2 overflow-y-auto">{source.pressure.map(row => <div key={row.status+row.criticality}><dt className="text-sm text-muted">{tEnum('incident.status', row.status)} · {tEnum('incident.criticality', row.criticality)}</dt><dd className="num">{row.incidents}</dd></div>)}</dl><p className="text-xs text-muted">{t('overviewUi.slaCoverage', { known: source.coverage.sla_known, total: source.coverage.sla_open })}</p></>}
        </Block>
        <div className="min-w-0 xl:col-span-2"><Block enabled={run !== null} id="shift" title={t('overviewUi.shift')} to={`/engine?${scopeQuery}`}><details><summary className="cursor-pointer rounded focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand">{t('overviewUi.expandShift')}</summary><p className="my-3 text-sm text-muted">{t('overviewUi.shiftHint')}</p>{source?.shift.items.length ? <ol className="grid gap-3 md:grid-cols-2">{source.shift.items.map((item, n) => <li key={`${item.agent_run_id}-${item.node}-${n}`} className="rounded border border-line p-3"><div className="flex flex-wrap items-center gap-2"><Link className="font-mono text-sm text-brand underline" to={`/engine/${item.agent_run_id}?${scopeQuery}`}>#{item.agent_run_id}</Link><Badge>{item.mode === 'unknown' ? t('overviewUi.unknownMode') : item.mode}</Badge>{item.public_id && <Link className="text-sm text-brand underline" to={`${ROUTES.journeyObject(item.public_id)}?${scopeQuery}`}>{item.public_id}</Link>}</div><p className="mt-2 text-sm">{item.text}</p></li>)}</ol> : <Empty title={t('overviewUi.noSummary')} />}{source?.shift.truncated && <p className="mt-2 text-sm text-muted">{t('overviewUi.summaryLimit', { total: source.shift.total, limit: source.shift.limit })}</p>}</details></Block></div>
      </div>
    </div>
  </div>
}
