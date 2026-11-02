import { SourcePlatformBadge } from '@/shared/components/SourcePlatformBadge'
import { CabinetNightDigest } from './CabinetNightDigest'
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { Link, useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, patch, type Schemas } from '@/shared/api/client'
import { useSimRuns, useRefs } from '@/shared/api/hooks'
import { useViewPreset, type ViewRole } from '@/shared/layout/preset'
import { useUndo } from '@/shared/ui/undo'
import { Drawer, Empty, ErrorBox, Skeleton } from '@/shared/ui'
import { useCabinetEvents, useCabinetOverview, signalsOptions, type CabinetSignal, type CabinetHeaders, type CabinetScope, type SignalFilters } from './api'
import { CabinetChart } from './CabinetChart'
import { CabinetMap } from './CabinetMap'
import { CabinetCalculator } from './CabinetCalculator'
import { compactMoney, cabinetPercent } from './format'
import { CabinetFeed, CabinetSignalDrawer, SignalLevel, SignalLinks } from './CabinetSignals'
import { fmtSimMoscow } from '@/shared/lib/format'
import { ProductLine, SignalStatus } from '@/shared/contracts/enums'
import { tEnum } from '@/shared/i18n'

export function CabinetPage() {
  const { t, i18n } = useTranslation()
  const { productLine } = useParams()
  const [params, setParams] = useSearchParams()
  const navigate = useNavigate()
  const location = useLocation()
  const cache = useQueryClient()
  const { role, demonstrator, setRole, setDemonstrator } = useViewPreset()
  const [binding, setBinding] = useState(() => localStorage.getItem('cx.ui.productLine') ?? productLine ?? '')
  const [selectedSignal, setSelectedSignal] = useState<CabinetSignal | null>(null)
  const [selectedContext, setSelectedContext] = useState('')
  const [calculator, setCalculator] = useState(false)
  const [bindingDraft, setBindingDraft] = useState(binding)
  const line = params.get('product_line') ?? productLine
  const period = (params.get('period') ?? 'week') as CabinetScope['period']
  const runId = params.get('run_id') ?? 'current'
  const region = params.get('region')
  const scope: CabinetScope = { product_line: line, period, run_id: runId }
  const bound = Object.values(ProductLine).find(code => code === binding)
  const headers: CabinetHeaders = { 'X-Cx-Role': role, ...(bound ? { 'X-Cx-Product-Line': bound } : {}) }
  const scopeKey = JSON.stringify({ scope, headers })
  const routeScope = JSON.stringify([location.pathname, line, period, runId])
  const liveScope = useRef<{ scope: string; route: string } | null>({ scope: scopeKey, route: routeScope })
  liveScope.current = { scope: scopeKey, route: routeScope }
  useLayoutEffect(() => { liveScope.current = { scope: scopeKey, route: routeScope }; return () => { liveScope.current = null } }, [scopeKey, routeScope])
  const offerLocalUndo = (restore: () => void) => useUndo.getState().offer(() => { if (liveScope.current?.scope === scopeKey) restore() })
  const visibleSignal = selectedContext === scopeKey ? selectedSignal : null
  const openSignal = (item: CabinetSignal) => { setSelectedContext(scopeKey); setSelectedSignal(item) }
  const overview = useCabinetOverview(scope, headers)
  const headerData = overview.isError ? undefined : overview.data
  const roles = useQuery({ queryKey: ['cabinet-roles'], queryFn: () => api<Schemas['CabinetRoles']>('/api/roles'), staleTime: Infinity })
  const runs = useSimRuns()
  const channels = useRefs('channels')
  const filters: SignalFilters = { ...scope, region: region ?? undefined, status: params.get('status') || undefined, channel: params.get('channel') || undefined, red_words: params.get('red_words') ?? undefined, sort: (params.get('sort') ?? 'date') as SignalFilters['sort'], direction: (params.get('direction') ?? 'desc') as SignalFilters['direction'], limit: 20, offset: Number(params.get('offset') ?? 0) }
  const table = useQuery(signalsOptions(filters, headers))
  const recent = useQuery(signalsOptions({ ...scope, region: region ?? undefined, red_words: filters.red_words, limit: 20, sort: 'date', direction: 'desc' }, headers))
  const regional = useQuery({ ...signalsOptions({ ...scope, region: region ?? undefined, red_words: filters.red_words, limit: 20, sort: 'date', direction: 'desc' }, headers), enabled: Boolean(region) })
  const visibility = useMutation({ mutationFn: (value: 'soft' | 'strict') => patch('/api/settings', { cabinet: { visibility: value } }), onSuccess: () => cache.invalidateQueries({ queryKey: ['cabinet'] }) })
  const report = useMutation({ mutationFn: () => api('/api/cabinet/report', { query: { ...scope, product_line: selectedLine?.code }, headers }) })
  useCabinetEvents()
  useEffect(() => { setSelectedSignal(null); setCalculator(false) }, [line, role, binding, runId])
  const update = (key: string, value: string | null) => {
    const previous = params.toString(), next = new URLSearchParams(params)
    if (value) next.set(key, value); else next.delete(key)
    if (key !== 'offset') next.delete('offset')
    if (next.toString() === previous) return
    setParams(next, { replace: true })
    if (key === 'run_id' || key === 'period') useUndo.getState().dismiss()
    else offerLocalUndo(() => setParams(previous, { replace: true }))
  }
  const changeLine = (code: string) => {
    if (code !== 'all') { localStorage.setItem('cx.ui.productLine', code); setBinding(code); setBindingDraft(code) }
    const next = new URLSearchParams(params); next.delete('region'); next.delete('offset'); next.delete('product_line')
    if (code === 'all') next.set('product_line', 'all')
    navigate({ pathname: code === 'all' ? '/cabinet' : `/cabinet/${encodeURIComponent(code)}`, search: next.toString() })
  }
  const changeRole = (next: ViewRole) => {
    const previous = { role, demonstrator, binding, bindingDraft, storedBinding: localStorage.getItem('cx.ui.productLine'), params: params.toString() }
    setRole(next)
    useUndo.getState().offer(() => { if (liveScope.current?.route !== routeScope) return; setRole(previous.role); setDemonstrator(previous.demonstrator); setBinding(previous.binding); setBindingDraft(previous.bindingDraft); if (previous.storedBinding !== null) localStorage.setItem('cx.ui.productLine', previous.storedBinding); else localStorage.removeItem('cx.ui.productLine'); setParams(previous.params, { replace: true }) })
  }
  const selectedRegion = overview.data?.regions.find(row => row.code === region)
  const selectedLine = overview.data?.product_lines.find(row => row.code === (line && line !== 'all' ? line : overview.data.scope.product_lines?.length === 1 ? overview.data.scope.product_lines[0] : undefined))
  const branchProducts: string[] = [ProductLine.DEPOSITS, ProductLine.MORTGAGE, ProductLine.LOANS, ProductLine.CREDIT_CARDS, ProductLine.DEBIT_CARDS, ProductLine.INSURANCE, ProductLine.BRANCHES_SERVICE]
  const showCsi = !selectedLine || branchProducts.includes(selectedLine.code) || (overview.data?.csi.responses ?? 0) > 0
  const regionNames = useMemo(() => new Map(overview.data?.regions.map(row => [row.code, i18n.language.startsWith('en') ? row.name_en : row.name_ru])), [overview.data?.regions, i18n.language])
  const clearFilters = () => { if (!['region', 'status', 'channel', 'red_words', 'sort', 'direction', 'offset'].some(key => params.has(key))) return; const previous = params.toString(); setParams(next => { const result = new URLSearchParams(next); ['region', 'status', 'channel', 'red_words', 'sort', 'direction', 'offset'].forEach(key => result.delete(key)); return result }, { replace: true }); offerLocalUndo(() => setParams(previous, { replace: true })) }
  return <div className="h-full min-w-0 overflow-y-auto p-3 sm:p-5" data-cabinet>
    <div className="mx-auto max-w-[1600px] space-y-5">
      <section className="card space-y-3 p-4" data-block="cabinet-header">
        <h1 className="text-xl font-semibold">{t('cabinet.title')}</h1>
        <p className="text-sm text-muted">{t('cabinet.presetHint')}</p>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
          <label className="min-w-0 text-sm">{t('shell.role')}<select className="input mt-1 w-full" value={role} onChange={event => changeRole(event.target.value as ViewRole)}>{roles.data?.items.map(item => <option key={item.code} value={item.code}>{i18n.language.startsWith('en') ? item.name_en : item.name_ru}</option>)}</select></label>
          <label className="min-w-0 text-sm">{t('cabinet.productLine')}<select className="input mt-1 w-full" value={line ?? (headerData?.scope.product_lines?.length === 1 ? headerData.scope.product_lines[0] : 'all')} onChange={event => changeLine(event.target.value)} disabled={!headerData}>{headerData && (headerData.scope.visibility !== 'strict' || !['product_manager', 'product_head'].includes(role)) ? <option value="all">{t('cabinet.allLines')}</option> : null}{headerData?.product_lines.map(item => <option key={item.code} value={item.code}>{i18n.language.startsWith('en') ? item.name_en : item.name_ru}{item.owner_is_proxy ? ' *' : ''}</option>)}</select></label>
          <label className="text-sm">{t('cabinet.period')}<select className="input mt-1 w-full" value={period} onChange={event => update('period', event.target.value)}>{(['day', 'week', 'month', 'quarter'] as const).map(value => <option key={value} value={value}>{t(`cabinet.periods.${value}`)}</option>)}</select></label>
          <label className="min-w-0 text-sm">{t('cabinet.run')}<select className="input mt-1 w-full" value={runId} onChange={event => update('run_id', event.target.value)}><option value="current">{t('cabinet.currentRun')}</option><option value="all">{t('cabinet.allRuns')}</option>{runs.data?.items?.map(item => <option key={item.id} value={item.id}>{item.id} · {item.label}</option>)}</select></label>
          <label className="text-sm">{t('cabinet.visibility')}<select className="input mt-1 w-full" value={headerData?.scope.visibility ?? ''} disabled={!headerData || visibility.isPending} onChange={event => visibility.mutate(event.target.value as 'soft' | 'strict')}><option value="" disabled>—</option><option value="soft">{t('cabinet.soft')}</option><option value="strict">{t('cabinet.strict')}</option></select></label>
        </div>
        {role === 'product_manager' && (!bound || overview.isError) && <label className="block text-sm">{t('cabinet.bindDirection')}<input className="input mt-1" value={bindingDraft} onChange={event => setBindingDraft(event.target.value)} onBlur={() => { setBinding(bindingDraft); localStorage.setItem('cx.ui.productLine', bindingDraft) }} onKeyDown={event => { if (event.key === 'Enter') { setBinding(bindingDraft); localStorage.setItem('cx.ui.productLine', bindingDraft) } }} /></label>}
        <button className="btn" disabled={!selectedLine || overview.isError || report.isPending} onClick={() => report.mutate()}>{t('cabinet.report')}</button>
        {headerData?.scope.product_lines?.length === 0 && role === 'product_head' && <p className="text-sm text-muted">{t('cabinet.noConfiguredLines')}</p>}
        {headerData && <p className="text-sm text-muted">{t('cabinet.periodBounds', { from: fmtSimMoscow(headerData.scope.since_sim), to: fmtSimMoscow(headerData.scope.sim_time) })}</p>}
        {visibility.isError && <ErrorBox error={visibility.error} />}{report.isError && <ErrorBox error={report.error} />}{roles.isError && <ErrorBox error={roles.error} />}
      </section>
      {overview.isPending ? <Skeleton className="h-52" /> : overview.isError ? <ErrorBox error={overview.error} /> : <>
        <section className="card p-4" data-block="cabinet-kpi"><h2 className="mb-3 font-semibold">{t('cabinet.kpi')}</h2><dl className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
          {[[t('cabinet.signals'), overview.data.kpi.signals, ''], [t('cabinet.negative'), cabinetPercent(overview.data.kpi.negative_share, i18n.language), ''], [t('cabinet.critical'), cabinetPercent(overview.data.kpi.critical_share, i18n.language), ''], [t('cabinet.loss'), overview.data.kpi.potential_loss_rub == null ? '—' : `−${compactMoney(overview.data.kpi.potential_loss_rub, i18n.language)}`, overview.data.kpi.potential_loss_rub == null ? 'text-muted' : 'text-danger'], [t('cabinet.prevented'), compactMoney(overview.data.kpi.prevented_loss_rub, i18n.language), overview.data.kpi.prevented_loss_rub == null ? 'text-muted' : overview.data.kpi.prevented_loss_rub < 0 ? 'text-danger' : 'text-ok']].map(([label, value, tone]) => <div key={label}><dt className="text-sm text-muted">{label}</dt><dd className={`num mt-1 text-2xl font-semibold ${tone}`}>{value}</dd></div>)}
        </dl><p className="mt-3 text-sm text-muted">{t('cabinet.coverage', { sentiment: overview.data.kpi.sentiment_known, all: overview.data.kpi.signals, mapped: overview.data.kpi.mapped, economics: overview.data.kpi.economics_known, incidents: overview.data.kpi.incidents })}</p><p className="text-sm text-muted">{t('cabinet.nullHint')}</p></section>
        <section className="card space-y-3 p-4" data-block="cabinet-map"><h2 className="font-semibold">{t('cabinet.map')}</h2><div className="grid min-w-0 gap-4 lg:grid-cols-[minmax(0,1fr)_18rem]">
          <CabinetMap regions={overview.data.regions} selected={region} onSelect={code => update('region', code)} onPrefetch={code => { void cache.prefetchQuery(signalsOptions({ ...scope, region: code, red_words: filters.red_words, limit: 20, sort: 'date', direction: 'desc' }, headers)) }} />
          <div className="min-w-0 space-y-3"><h3 className="font-medium">{t('cabinet.topRegions')}</h3><ol className="space-y-2">{overview.data.top_regions.map(row => <li key={row.code}><button className="btn btn-sm w-full justify-between" onClick={() => update('region', row.code)}>{regionNames.get(row.code)}<span className="num">{row.signals}</span></button></li>)}</ol><p className="text-sm text-muted">{t('cabinet.noGeoCount', { n: overview.data.kpi.no_geo })}</p>{selectedRegion && <div className="space-y-2 rounded border border-line p-3" aria-label={t('cabinet.regionPanel')}><h3 className="font-semibold">{regionNames.get(selectedRegion.code)}</h3><p>{t('cabinet.signals')}: {selectedRegion.signals}</p><button className="btn btn-sm" onClick={() => setCalculator(true)}>{t('cabinet.calculateLoss')}</button><button className="btn btn-sm" onClick={() => update('region', null)}>{t('cabinet.resetRegion')}</button>{regional.isError ? <ErrorBox error={regional.error} /> : regional.isPending ? <Skeleton className="h-12" /> : <ul className="space-y-2">{regional.data.items.slice(0, 5).map(item => <li key={item.id}><div className="flex flex-wrap items-center gap-2"><SignalLevel value={item.criticality} /><button className="text-brand underline" onClick={() => openSignal(item)}>{item.public_id}</button></div><p className="mt-1 text-sm text-muted">{t('cabinet.columns.status')}: {tEnum('signal.status', item.status)} · {tEnum('channel', item.channel_code)}</p><SourcePlatformBadge platform={item.source_platform} /></li>)}</ul>}</div>}</div>
        </div><p className="text-sm text-muted">{t('cabinet.mapHint')}</p></section>
        <section className="card space-y-4 p-4" data-block="cabinet-signals"><CabinetNightDigest scope={scope} headers={headers} redWords={filters.red_words} /><h2 className="font-semibold">{t('cabinet.recent')}</h2>
          {recent.isError ? <ErrorBox error={recent.error} /> : recent.isPending ? <Skeleton className="h-32" /> : <CabinetFeed rows={recent.data.items} data={overview.data} runId={runId} onOpen={openSignal} />}
          <h3 className="font-semibold">{t('cabinet.allSignals')}</h3>{role === 'compliance_officer' && !params.has('red_words') && <p className="text-sm">{t('cabinet.compliancePresetActive')} <button className="text-brand underline" onClick={() => update('red_words', 'false')}>{t('cabinet.clearCompliancePreset')}</button></p>}{role === 'compliance_officer' && params.get('red_words') === 'false' && <button className="btn btn-sm" onClick={() => update('red_words', null)}>{t('cabinet.restoreCompliancePreset')}</button>}<div className="flex flex-wrap items-end gap-2">
            <label className="text-sm">{t('cabinet.region')}<select className="input block" value={region ?? ''} onChange={event => update('region', event.target.value)}><option value="">{t('cabinet.any')}</option>{overview.data.regions.map(row => <option key={row.code} value={row.code}>{regionNames.get(row.code)}</option>)}</select></label>
            <label className="text-sm">{t('cabinet.status')}<select className="input block" value={params.get('status') ?? ''} onChange={event => update('status', event.target.value)}><option value="">{t('cabinet.any')}</option>{Object.values(SignalStatus).map(code => <option key={code} value={code}>{tEnum('signal.status', code)}</option>)}</select></label>
            <label className="text-sm">{t('cabinet.channel')}<select className="input block" value={params.get('channel') ?? ''} onChange={event => update('channel', event.target.value)}><option value="">{t('cabinet.any')}</option>{channels.data?.map(item => <option key={item.code} value={item.code}>{i18n.language.startsWith('en') ? item.name_en ?? item.name_ru : item.name_ru}</option>)}</select></label>
            <label className="text-sm"><input type="checkbox" checked={params.get('red_words') === 'true'} onChange={event => update('red_words', event.target.checked ? 'true' : null)} /> {t('cabinet.onlyRedWords')}</label>
            <label className="text-sm">{t('cabinet.sort')}<select className="input block" value={filters.sort} onChange={event => update('sort', event.target.value)}>{(['date', 'level', 'region'] as const).map(value => <option key={value} value={value}>{t(`cabinet.sorts.${value}`)}</option>)}</select></label>
            <button className="btn btn-sm" onClick={() => update('direction', filters.direction === 'asc' ? 'desc' : 'asc')}>{t(filters.direction === 'asc' ? 'cabinet.ascending' : 'cabinet.descending')}</button><button className="btn btn-sm" onClick={clearFilters}>{t('cabinet.resetFilters')}</button>
          </div>
          {table.isError ? <ErrorBox error={table.error} /> : table.isPending ? <Skeleton className="h-40" /> : !table.data.items.length ? <Empty title={t('cabinet.noSignals')} /> : <><p className="text-sm">{t('cabinet.total', { n: table.data.total })}</p><div className="overflow-x-auto"><table className="w-full min-w-[720px] text-left text-sm"><thead><tr>{['signal', 'level', 'summary', 'region', 'status', 'date'].map(key => <th key={key} className="px-2 py-2">{t(`cabinet.columns.${key}`)}</th>)}</tr></thead><tbody>{table.data.items.map(item => <tr key={item.id} className="border-t border-line"><td className="p-2"><SignalLinks item={item} runId={runId} /></td><td className="p-2"><SignalLevel value={item.criticality} /></td><td className={`max-w-sm p-2 ${item.flags.includes('red_word') ? 'border-l-[4px] border-l-danger' : ''}`}><button className="text-left underline decoration-line" onClick={() => openSignal(item)}>{item.summary}</button></td><td className="p-2">{item.region_code ? regionNames.get(item.region_code) ?? item.region_code : '—'}</td><td className="p-2">{tEnum('signal.status', item.status)}</td><td className="whitespace-nowrap p-2">{fmtSimMoscow(item.received_sim)}</td></tr>)}</tbody></table></div><div className="flex gap-2"><button className="btn btn-sm" disabled={!filters.offset} onClick={() => update('offset', String(Math.max(0, (filters.offset ?? 0) - 20)))}>{t('cabinet.previous')}</button><button className="btn btn-sm" disabled={table.data.next_offset == null} onClick={() => update('offset', String(table.data.next_offset))}>{t('cabinet.next')}</button></div></>}
        </section>
        <section className="card space-y-3 p-4" data-block="cabinet-charts"><h2 className="font-semibold">{t('cabinet.analytics')}</h2><CabinetChart data={overview.data} /></section>
        {showCsi && <section className="card space-y-3 p-4" data-block="cabinet-csi"><h2 className="font-semibold">{t('cabinet.csi')}</h2><p>{t('cabinet.csiSummary', { responses: overview.data.csi.responses, branches: overview.data.csi.branches ?? '—', wait: overview.data.csi.average_wait_min == null ? '—' : new Intl.NumberFormat(i18n.language, { maximumFractionDigits: 1 }).format(overview.data.csi.average_wait_min) })}</p><p className="text-sm text-muted">{t('cabinet.csiCoverage', { branch: overview.data.csi.branch_known, wait: overview.data.csi.wait_known, total: overview.data.csi.responses })}</p><p className="text-sm text-muted">{t('cabinet.csiHint')}</p><Link className="btn btn-sm" to={`/csi?${new URLSearchParams({ ...(line ? { product_line: line } : {}), run_id: runId })}`}>{t('cabinet.openCsi')}</Link></section>}
        <section className="card space-y-3 p-4" data-block="cabinet-calculator"><h2 className="font-semibold">{t('cabinet.calculator')}</h2><p className="text-sm text-muted">{selectedLine ? (i18n.language.startsWith('en') ? selectedLine.name_en : selectedLine.name_ru) : t('cabinet.chooseDirectionForRate')}</p><button className="btn" onClick={() => setCalculator(true)}>{t('cabinet.openCalculator')}</button><Drawer open={calculator} onClose={() => { setCalculator(false); offerLocalUndo(() => setCalculator(true)) }} title={t('cabinet.calculator')}><div className="p-4"><CabinetCalculator line={selectedLine} region={selectedRegion} /></div></Drawer></section>
      </>}
    </div>
    <CabinetSignalDrawer item={visibleSignal} onClose={() => { const previous = selectedSignal; setSelectedSignal(null); offerLocalUndo(() => setSelectedSignal(previous)) }} runId={runId} />
  </div>
}
