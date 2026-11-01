import { useMobileLayout } from '@/shared/layout/device-store'
import { EntityFilter } from '@/shared/components/EntityFilter'
import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { init } from 'echarts'
import { api, type Schemas } from '@/shared/api/client'
import { useSimRuns, useSimState } from '@/shared/api/hooks'
import { fmtSim } from '@/shared/lib/format'
import { formatMoney as fmtRub } from './money'
import { EvidencePanel, CaseEvidence } from './EvidencePanel'
import { ProductFilter, type ProductSelection } from './ProductFilter'
import { tEnum } from '@/shared/i18n'
import { ErrorBox, Modal, Skeleton } from '@/shared/ui'
import { useWs } from '@/shared/ws/client'

type Total = Schemas['FinancialImpactTotal']
type Detail = Schemas['FinancialImpactDetail']
type Period = Total['period']

function AnimatedMoney({ value }: { value: number }) {
  const [shown, setShown] = useState(value)
  const previous = useRef(value)
  useEffect(() => {
    const from = previous.current
    previous.current = value
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) { setShown(value); return }
    let frame = 0
    const start = performance.now()
    const tick = (now: number) => {
      const progress = Math.min(1, (now - start) / 650)
      setShown(from + (value - from) * (1 - (1 - progress) ** 3))
      if (progress < 1) frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [value])
  return <span className="num">{fmtRub(shown)}</span>
}

function GrowthChart({ series }: { series: Total['series'] }) {
  const el = useRef<HTMLDivElement>(null)
  const { t, i18n } = useTranslation()
  const mobile = useMobileLayout()
  useEffect(() => {
    if (!el.current) return
    const textColor = getComputedStyle(el.current).color
    const chart = init(el.current, undefined, { renderer: 'svg' })
    chart.setOption({
      color: ['#21A038', '#0098F8'],
      tooltip: { trigger: 'axis', valueFormatter: (v: number) => fmtRub(v) },
      legend: { type: 'scroll', data: [t('finance.saved'), t('finance.net')], textStyle: { color: textColor } },
      grid: { left: mobile ? 62 : 80, right: mobile ? 8 : 20, top: 48, bottom: 36 },
      xAxis: { type: 'category', data: series.map((p) => mobile ? fmtSim(p.time, 'dd.MM') : fmtSim(p.time)), boundaryGap: false, axisLabel: { color: textColor } },
      yAxis: { type: 'value', axisLabel: { color: textColor, ...(mobile ? { formatter: (v: number) => new Intl.NumberFormat(i18n.language, { notation: 'compact', maximumFractionDigits: 1 }).format(v) } : {}) } },
      series: [
        { name: t('finance.saved'), type: 'line', step: 'end', data: series.map((p) => p.saved_rub), areaStyle: { opacity: 0.08 } },
        { name: t('finance.net'), type: 'line', step: 'end', data: series.map((p) => p.net_rub) },
      ],
    })
    const observer = new ResizeObserver(() => chart.resize())
    observer.observe(el.current)
    const themeObserver = new MutationObserver(() => {
      const color = el.current ? getComputedStyle(el.current).color : textColor
      chart.setOption({ legend: { textStyle: { color } }, xAxis: { axisLabel: { color } }, yAxis: { axisLabel: { color } } })
    })
    themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['class', 'data-mode', 'data-pack'] })
    return () => { observer.disconnect(); themeObserver.disconnect(); chart.dispose() }
  }, [series, t, i18n.language, mobile])
  return <div ref={el} className="h-64 w-full" role="img" aria-label={t('finance.chart')} />
}

export function FinancePage() {
  const mobile = useMobileLayout()
  const [entityQuery, setEntityQuery] = useState('')
  const { t } = useTranslation()
  const [products, setProducts] = useState<ProductSelection>({ mode: 'all', codes: [] })
  const [period, setPeriod] = useState<Period>('live')
  const [run, setRun] = useState('current')
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')
  const [probability, setProbability] = useState(100)
  const [fine, setFine] = useState(50000)
  const [offset, setOffset] = useState(0)
  const [incident, setIncident] = useState<string | null>(null)
  const runs = useSimRuns()
  const state = useSimState()
  const live = useWs((s) => s.sim)
  const wsStatus = useWs((s) => s.status)
  const currentRun = live !== null ? live.current_run_id : state.data?.current_run_id
  const selectedRun = run === 'current' ? currentRun : Number(run)
  useEffect(() => { setOffset(0); setIncident(null) }, [selectedRun])
  useEffect(() => { setOffset(0); setIncident(null) }, [entityQuery])
  const validDates = period !== 'custom' || (!!start && !!end && end > start)
  const query = useQuery({
    queryKey: ['metrics', 'finance', run, selectedRun ?? null, period, start, end, probability, fine, offset, products, entityQuery],
    queryFn: () => api<Total>('/api/v1/finance/impact/total', { query: {
      q: entityQuery || undefined, run_id: run, period, product_mode: products.mode, product_codes: products.codes, probability_percent: probability, fine_per_case_rub: fine, offset,
      ...(period === 'custom' ? { start_date: `${start}:00Z`, end_date: `${end}:00Z` } : {}),
    } }),
    enabled: validDates,
    refetchInterval: 5000,
  })
  const d = query.data
  useEffect(() => { setOffset(0); setIncident(null) }, [d?.run_id])
  const detail = useQuery({
    queryKey: ['metrics', 'finance-detail', d?.run_id ?? null, incident, probability, fine],
    queryFn: () => api<Detail>(`/api/v1/finance/impact/incident/${incident}`, { query: { run_id: d?.run_id ?? run, probability_percent: probability, fine_per_case_rub: fine } }),
    enabled: incident !== null,
  })
  const change = () => { setOffset(0); setIncident(null) }
  return <div className="finance-page h-full overflow-auto p-4 md:p-6">
    <div className="mx-auto flex max-w-7xl flex-col gap-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div><h1 className="text-2xl font-semibold">{t('finance.title')}</h1><p className="mt-1 text-sm text-muted">{t('finance.subtitle')}</p></div>
        <label className="flex max-w-full items-center gap-2 text-xs text-muted">{t('finance.run')}<select aria-label={t('finance.run')} className="input min-w-0 max-w-full flex-1" value={run} onChange={(e) => { setRun(e.target.value); change() }}>
          <option value="current">{t('finance.current')}</option>
          {runs.data?.items?.map((r) => <option key={r.id} value={r.id}>{r.label || r.id} · {r.status}</option>)}
        </select></label>
      </div>
      <div className="flex flex-wrap items-center gap-2" aria-label={t('finance.period')}>
        {(['live', 'day', 'week', 'month', 'custom'] as const).map((p) => <button key={p} className={`btn btn-sm ${period === p ? 'btn-primary' : ''}`} aria-pressed={period === p} onClick={() => { setPeriod(p); change() }}>{t(`finance.periods.${p}`)}</button>)}
        {period === 'custom' && <>
          <label className="text-xs">{t('finance.from')} <input className="input" type="datetime-local" aria-label={t('finance.from')} value={start} onChange={(e) => { setStart(e.target.value); change() }} /></label>
          <label className="text-xs">{t('finance.until')} <input className="input" type="datetime-local" aria-label={t('finance.until')} value={end} onChange={(e) => { setEnd(e.target.value); change() }} /></label>
        </>}
        <span className="ml-auto text-xs text-muted">{t(wsStatus === 'open' ? 'finance.connected' : 'finance.polling')}</span>
      </div>
      <EntityFilter onChange={setEntityQuery} />
      <ProductFilter value={products} onChange={value => { setProducts(value); change() }} />
      <p className="text-xs text-muted">{t('finance.timeHint')} · <Link className="text-info underline" to="/economics">{t('calculator.title')}</Link></p>
      {!validDates && <p role="status" className="text-warn">{t('finance.invalidDates')}</p>}
      {query.isError && <ErrorBox error={query.error} />}
      {query.isLoading && <Skeleton className="h-36" />}
      {validDates && d && <>
        {(d.stale_calculations > 0 || d.missing_calculations > 0) && <p role="status" className="rounded border border-warn p-3 text-sm text-warn">{t('finance.incomplete', { missing: d.missing_calculations, stale: d.stale_calculations })}</p>}
        <section className="card p-5" aria-label={t('finance.model')}>
          <div className="text-xs uppercase tracking-wide text-muted">{t('finance.model')}</div>
          <h2 className="mt-2 text-sm">{t('finance.saved')}</h2>
          <div className="my-3 text-4xl font-semibold text-ok md:text-5xl"><AnimatedMoney key={`${d.run_id}-${period}-${start}-${end}`} value={d.total_saved_rub} /></div>
          <p className="text-xs text-muted">{t('finance.estimate')}</p>
          <div className="mt-4 grid grid-cols-2 gap-4 md:grid-cols-4">
            <Metric label={t('finance.refund')} value={fmtRub(d.refund_rub)} />
            <Metric label={t('finance.net')} value={fmtRub(d.net_effect_rub)} />
            <Metric label={t('finance.resolved')} value={String(d.incidents_resolved)} />
            <Metric label={t('finance.top')} value={d.top_product_saved ?? '—'} />
          </div>
        </section>
        <section className="grid gap-3 md:grid-cols-2" aria-label={t('finance.comparison')}>
          <div className="card p-4"><h2 className="font-semibold">{t('finance.scenario')}</h2>
            <label className="my-3 flex items-center gap-2 text-sm">{t('finance.probability')} <input className="input w-24" type="number" min="0" max="100" value={probability} onChange={(e) => { const v = Number(e.target.value); if (Number.isFinite(v) && v >= 0 && v <= 100) { setProbability(v); change() } }} /> %</label>
            <p className="text-2xl num">{fmtRub(d.scenario_saved_rub)}</p><p className="text-sm text-muted">{t('finance.net')}: {fmtRub(d.scenario_net_rub)}</p>
            <p className="mt-2 text-xs text-muted">{t('finance.scenarioHint')}</p>
          </div>
          <div className="card p-4"><h2 className="font-semibold">{t('finance.fineScenario')}</h2>
            <label className="my-3 flex items-center gap-2 text-sm">{t('finance.fine')} <input className="input w-32" type="number" min="0" max="100000000" value={fine} onChange={(e) => { const v = Number(e.target.value); if (Number.isFinite(v) && v >= 0 && v <= 100000000) { setFine(v); change() } }} /></label>
            <p className="text-2xl num">{fmtRub(d.scenario_saved_rub + d.scenario_fine_rub)}</p><p className="text-sm text-muted">{t('finance.net')}: {fmtRub(d.scenario_with_fine_net_rub)}</p>
            <p className="mt-2 text-xs text-muted">{t('finance.fineHint', { count: d.fine_cases })}</p>
          </div>
        </section>
        <EvidencePanel entityQuery={entityQuery} runId={d.run_id} period={period} start={start} end={end} products={products} />
        <section className="card p-4"><h2 className="font-semibold">{t('finance.chart')}</h2>
          {d.series.length ? <GrowthChart series={d.series} /> : <p className="py-10 text-center text-muted">{t('finance.empty')}</p>}
        </section>
        <section className="card overflow-hidden"><h2 className="p-4 font-semibold">{t('finance.ledger')}</h2>
          {mobile ? <ul className="finance-case-list divide-y divide-line">{d.items.map(item => <li key={item.incident_id} className="space-y-3 p-4">
            <div className="flex flex-wrap items-center justify-between gap-2"><button className="btn btn-sm text-info" onClick={() => setIncident(item.public_id)}>{item.public_id}</button><span className="text-xs text-muted">{fmtSim(item.resolved_sim)}</span></div>
            <p className="text-sm">{item.product_name} · {tEnum('incidentType', item.incident_type)}</p>
            <p className="text-xs text-muted">{t('finance.client')}: {item.client_public_id ?? '—'} · LTV {fmtRub(item.client_ltv_rub)}</p>
            <dl className="space-y-2">{([['saved', item.saved_rub], ['refund', item.refund_rub], ['net', item.net_rub]] as const).map(([key, value]) => <div key={key} className="flex flex-wrap justify-between gap-2 text-sm"><dt className="text-muted">{t(`finance.${key}`)}</dt><dd className="num font-semibold">{item.missing ? '—' : fmtRub(value)}</dd></div>)}</dl>
            <p className="text-xs">{tEnum('incident.status', item.status)}{(item.stale || item.missing) && <span className="ml-2 text-warn">{t('finance.stale')}</span>}</p>
          </li>)}</ul> : <div className="overflow-x-auto"><table className="w-full text-sm"><thead className="bg-raised text-left text-xs text-muted"><tr>
            {['time', 'case', 'product', 'client', 'saved', 'refund', 'net', 'status'].map((k) => <th key={k} className="p-3">{t(`finance.${k}`)}</th>)}
          </tr></thead><tbody className="divide-y divide-line">{d.items.map((item) => <tr key={item.incident_id}>
            <td className="whitespace-nowrap p-3">{fmtSim(item.resolved_sim)}</td>
            <td className="p-3"><button className="text-info underline" onClick={() => setIncident(item.public_id)}>{item.public_id}</button><div className="text-xs text-muted">{tEnum('incidentType', item.incident_type)}</div></td>
            <td className="p-3">{item.product_name}</td><td className="p-3">{item.client_public_id ?? '—'}<div className="text-xs text-muted">LTV {fmtRub(item.client_ltv_rub)}</div></td>
            <td className="p-3 num text-ok">{item.missing ? '—' : fmtRub(item.saved_rub)}</td><td className="p-3 num">{item.missing ? '—' : fmtRub(item.refund_rub)}</td><td className="p-3 num">{item.missing ? '—' : fmtRub(item.net_rub)}</td>
            <td className="p-3">{tEnum('incident.status', item.status)}{(item.stale || item.missing) && <div className="text-xs text-warn">{t('finance.stale')}</div>}</td>
          </tr>)}</tbody></table></div>}
          {!d.items.length && <p className="p-6 text-muted">{t('finance.empty')}</p>}
          <div className="flex items-center justify-end gap-3 border-t border-line p-3">
            <button className="btn btn-sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 25))}>{t('finance.previous')}</button>
            <span className="text-xs text-muted">{Math.min(offset + 1, d.incidents_resolved)}–{offset + d.items.length} / {d.incidents_resolved}</span>
            <button className="btn btn-sm" disabled={d.next_offset === null} onClick={() => setOffset(d.next_offset ?? 0)}>{t('finance.next')}</button>
          </div>
        </section>
      </>}
      <Modal open={incident !== null} onClose={() => setIncident(null)} title={`${t('finance.reason')} · ${incident ?? ''}`} width="max-w-2xl">
        {detail.isError && <ErrorBox error={detail.error} />}
        {detail.isLoading && <Skeleton className="h-36" />}
        {detail.data && <Explanation detail={detail.data} probability={probability} />}
      </Modal>
    </div>
  </div>
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div><div className="text-xs text-muted">{label}</div><div className="mt-1 text-lg num">{value}</div></div>
}

function Explanation({ detail: d, probability }: { detail: Detail; probability: number }) {
  const { t } = useTranslation()
  const c = d.calculation
  const scenario = d.scenario_saved_rub
  return <div className="space-y-3 text-sm">
    {(d.stale || d.missing) && <p className="text-warn">{t('finance.stale')}</p>}
    <p>{d.product_name} · {d.client_public_id ?? '—'} · {d.client_segment ?? '—'}</p>
    <h3 className="font-semibold">{t('finance.model')}</h3>
    {d.missing ? <p>{t('finance.noCalculation')}</p> : <>
      <p className="num">{c.formula_ru}</p>
      <p>{t('finance.retention')}: {fmtRub(c.potential_loss_rub)} × {c.retention_factor} = {fmtRub(d.saved_rub)} ({c.retention_source})</p>
      <p>{t('finance.net')}: {fmtRub(d.saved_rub)} − {fmtRub(d.refund_rub)} = {fmtRub(d.net_rub)}</p>
      <p className="text-xs text-muted">{c.rate_reason} · {c.rate_code} · {t('finance.computed')}: {fmtSim(c.computed_sim)}</p>
    </>}
    <h3 className="font-semibold">{t('finance.scenario')}</h3>
    <p className="num">1 × {probability}% × {fmtRub(d.scenario_base_rub, 3)} = {fmtRub(scenario)}</p>
    <p>{t('finance.net')}: {fmtRub(scenario)} − {fmtRub(d.refund_rub)} = {fmtRub(d.scenario_net_rub)}</p>
    <h3 className="font-semibold">{t('finance.fineScenario')}</h3>
    <p className="num">{fmtRub(scenario)} + {fmtRub(d.scenario_fine_rub)} − {fmtRub(d.refund_rub)} = {fmtRub(d.scenario_with_fine_net_rub)}</p>
    <p className="text-xs text-muted">{t('finance.scenarioHint')} {t('finance.fineHint', { count: d.fine_eligible ? 1 : 0 })}</p>
    <CaseEvidence detail={d} />
    <Link className="btn btn-sm" to={`/incidents/${d.incident_id}`}>{t('finance.openIncident')}</Link>
  </div>
}
