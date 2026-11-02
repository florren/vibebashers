import { useMemo, useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useRefs, useSimRuns } from '@/shared/api/hooks'
import { useViewPreset } from '@/shared/layout/preset'
import { IdLink } from '@/shared/components/IdLink'
import { Section, Empty, ErrorBox, SkeletonRows, Badge } from '@/shared/ui'
import { analyticsOptions, useBranchDirectory, useDirectionCatalog, type CsiScope } from './api'
import { CsiChart } from './Chart'
import { useCsiPalette } from './palette'
import { positionOption, probabilityOption, scatterOption, tenureOption, topOption } from './options'
import { RegionHeatmap } from './RegionHeatmap'

const selectClass = 'rounded-md border border-line bg-surface px-2 py-1.5 text-sm text-ink'
function DataTable({ headers, rows }: { headers: string[]; rows: ReactNode[][] }) {
  return <div className="overflow-x-auto p-3"><table className="w-full text-left text-sm"><thead><tr>{headers.map((header, index) => <th key={index} scope="col" className="p-2 text-xs text-muted">{header}</th>)}</tr></thead><tbody>{rows.map((row, index) => <tr key={index} className="border-t border-line">{row.map((cell, i) => <td key={i} className="p-2 align-top">{cell}</td>)}</tr>)}</tbody></table></div>
}
function Alternative({ children, label }: { children: ReactNode; label: string }) {
  return <details><summary className="cursor-pointer px-3 py-2 text-sm text-muted">{label}</summary>{children}</details>
}

export function CsiPage() {
  const { t, i18n } = useTranslation()
  const role = useViewPreset(state => state.role)
  const [binding, setBinding] = useState(() => localStorage.getItem('cx.ui.productLine') ?? '')
  const [params, setParams] = useSearchParams()
  // Явный некорректный scope доходит до API validation, а не расширяется до all.
  const scope: CsiScope = {
    run_id: params.get('run_id') ?? 'current',
    period: (params.get('period') ?? 'month') as CsiScope['period'],
    offset: Number(params.get('offset') ?? 0),
    ...(params.has('product_line') ? { product_line: params.get('product_line')! } : {}),
    ...(params.has('region_code') ? { region_code: params.get('region_code')! } : {}),
    ...(params.has('branch_id') ? { branch_id: Number(params.get('branch_id')) } : {}),
  }
  const headers = useMemo(() => ({ 'X-Cx-Role': role, ...(binding ? { 'X-Cx-Product-Line': binding } : {}) }), [role, binding])
  const snapshot = useQuery(analyticsOptions(scope, headers))
  const directory = useBranchDirectory({ product_line: scope.product_line, region_code: scope.region_code }, headers)
  const catalog = useDirectionCatalog(headers)
  const regions = useRefs('regions')
  const runs = useSimRuns()
  const colors = useCsiPalette()
  const number = (value: number | null | undefined) => value == null ? t('csi.unknown') : new Intl.NumberFormat(i18n.language, { maximumFractionDigits: 3 }).format(value)
  const navigate = (patch: Partial<CsiScope>) => {
    const next = new URLSearchParams(params)
    for (const [key, value] of Object.entries(patch)) {
      if (value === undefined) next.delete(key)
      else next.set(key, String(value))
    }
    setParams(next)
  }
  const update = (patch: Partial<CsiScope>) => navigate({ ...patch, offset: 0 })
  const text = (key: string) => t(key)
  const unknown = t('csi.unknown')
  const data = snapshot.data
  const branches = directory.data?.pages.flatMap(page => page.items) ?? []
  const trace = (kind: string, ref: string | number, label?: string) => <Link className="text-brand hover:underline font-mono text-xs" to={`/trace/${kind}/${encodeURIComponent(String(ref))}?run_id=${encodeURIComponent(scope.run_id)}`}>{label ?? ref}</Link>
  const probability = (axis: 'wait' | 'redirects') => {
    if (!data) return null
    const values = data.probabilities[axis]
    return <Section title={t('csi.probability.' + axis)}>
      <p className="p-3 text-sm">{t('csi.correlation', { rho: number(values.spearman), count: values.n_buckets })}</p>
      <CsiChart option={probabilityOption(values, colors, values.buckets.map(row => row.bucket))} label={t('csi.probability.' + axis)} />
      <DataTable headers={[t('csi.bucket'), t('csi.complaints'), t('csi.visits'), t('csi.probabilityLabel')]} rows={values.buckets.map(row => [row.bucket, number(row.complaints), number(row.visits), row.probability == null ? unknown : number(row.probability * 100) + '%'])} />
    </Section>
  }
  return <main className="space-y-4 p-3 md:p-5" aria-label={t('csi.title')}>
    <h1 className="text-xl font-semibold">{t('csi.title')}</h1>
    <p className="text-sm text-muted">{t('csi.description')}</p>
    <div className="flex flex-wrap items-end gap-3">
      <label className="grid gap-1 text-xs text-muted">{t('csi.run')}<select className={selectClass} value={scope.run_id} onChange={event => update({ run_id: event.target.value })}><option value="current">{t('csi.current')}</option><option value="all">{t('csi.allRuns')}</option>{!['current', 'all'].includes(scope.run_id) && !runs.data?.items?.some(run => String(run.id) === scope.run_id) && <option value={scope.run_id}>{t('csi.selectedId', { id: scope.run_id || unknown })}</option>}{runs.data?.items?.map(run => <option key={run.id} value={String(run.id)}>SR-{run.id} · {run.label}</option>)}</select></label>
      <label className="grid gap-1 text-xs text-muted">{t('csi.period')}<select className={selectClass} value={scope.period} onChange={event => update({ period: event.target.value as CsiScope['period'] })}>{(['day', 'week', 'month', 'quarter'] as const).map(period => <option key={period} value={period}>{t('csi.periods.' + period)}</option>)}</select></label>
      <label className="grid gap-1 text-xs text-muted">{t('csi.direction')}<select className={selectClass} value={scope.product_line ?? ''} onChange={event => update({ product_line: event.target.value || undefined, branch_id: undefined })}><option value="">{t('csi.all')}</option>{scope.product_line && !catalog.data?.some(line => line.code === scope.product_line) && <option value={scope.product_line}>{scope.product_line}</option>}{catalog.data?.map(line => <option key={line.code} value={line.code}>{i18n.language.startsWith('en') ? line.name_en ?? line.name_ru : line.name_ru}</option>)}</select></label>
      <label className="grid gap-1 text-xs text-muted">{t('csi.region')}<select className={selectClass} value={scope.region_code ?? ''} onChange={event => update({ region_code: event.target.value || undefined, branch_id: undefined })}><option value="">{t('csi.all')}</option>{scope.region_code && !regions.data?.some(region => region.code === scope.region_code) && <option value={scope.region_code}>{scope.region_code}</option>}{regions.data?.map(region => <option key={region.code} value={region.code}>{i18n.language.startsWith('en') ? region.name_en ?? region.name_ru : region.name_ru}</option>)}</select></label>
      <label className="grid gap-1 text-xs text-muted">{t('csi.branch')}<select className={selectClass} value={scope.branch_id ?? ''} onChange={event => update({ branch_id: event.target.value ? Number(event.target.value) : undefined })}><option value="">{t('csi.all')}</option>{scope.branch_id !== undefined && !branches.some(branch => branch.id === scope.branch_id) && <option value={scope.branch_id}>{t('csi.selectedId', { id: scope.branch_id })}</option>}{branches.map(branch => <option key={branch.id} value={branch.id}>{branch.code} · {branch.city_name}</option>)}</select></label>
      {directory.hasNextPage && <button className={selectClass} disabled={directory.isFetchingNextPage} onClick={() => void directory.fetchNextPage()}>{t('csi.moreBranches')}</button>}
      {['product_manager', 'product_head'].includes(role) && <label className="grid gap-1 text-xs text-muted">{t('csi.binding')}<input className={selectClass} value={binding} onChange={event => { const value = event.target.value; localStorage.setItem('cx.ui.productLine', value); setBinding(value) }} /></label>}
    </div>
    {(directory.error || catalog.error || regions.error || runs.error) && <ErrorBox error={directory.error ?? catalog.error ?? regions.error ?? runs.error} />}
    {snapshot.isPending && <SkeletonRows />}
    {snapshot.error && <ErrorBox error={snapshot.error} />}
    {data && <>
      <p className="text-xs text-muted">{t('csi.scopeTime', { since: data.scope.since_sim, until: data.scope.sim_time })} · {t('csi.coverage', { count: data.coverage.complaints, employee: data.coverage.employee_known, uncohorted: data.coverage.uncohorted })}</p>
      {data.coverage.complaints === 0 && <Empty title={t('csi.empty')} hint={t('csi.emptyHint')} />}
      <Section title={t('csi.table')} right={<span className="text-xs text-muted">{data.complaints.total}</span>}>
        <DataTable headers={[t('csi.ids'), t('csi.branch'), t('csi.position'), t('csi.wait'), t('csi.service'), t('csi.summary'), t('csi.path')]} rows={data.complaints.items.map(row => [<div className="grid gap-1">{<IdLink kind="signal" value={row.signal_ref} runId={scope.run_id} />}{row.csi_no && <IdLink kind="csi" value={row.csi_no} runId={scope.run_id} />}</div>, row.branch_id == null ? unknown : trace('branch', row.branch_id, row.branch_code ?? String(row.branch_id)), row.position ?? unknown, number(row.wait_min), number(row.service_min), <div className="max-w-xs break-words">{row.summary}<p className="mt-1 text-xs text-muted">{row.product_line_code ?? unknown} · {t('csi.directionSource.' + row.direction_source)}</p></div>, <Link className="text-brand hover:underline" to={`/journey/${encodeURIComponent(row.signal_ref)}?run_id=${encodeURIComponent(scope.run_id)}`}>{t('csi.path')}</Link>])} />
        <div className="flex justify-between gap-3 p-3"><button className={selectClass} disabled={scope.offset === 0} onClick={() => navigate({ offset: Math.max(0, scope.offset - 50) })}>{t('csi.previous')}</button><button className={selectClass} disabled={data.complaints.next_offset == null} onClick={() => navigate({ offset: data.complaints.next_offset ?? scope.offset })}>{t('csi.next')}</button></div>
      </Section>
      <div className="grid min-w-0 gap-4 xl:grid-cols-2">
        <Section title={t('csi.scatter')}><p className="p-3 text-xs text-muted">{t('csi.shown', { shown: data.scatter.shown, total: data.scatter.total })}</p><CsiChart option={scatterOption(data, colors, text)} label={t('csi.scatter')} /><Alternative label={t('csi.chartData')}><DataTable headers={[t('csi.ids'), t('csi.wait'), t('csi.service'), t('csi.criticality')]} rows={data.scatter.items.map(row => [trace('signal', row.signal_ref), number(row.wait_min), number(row.service_min), t('csi.level.' + (row.criticality ?? 'unknown'))])} /></Alternative></Section>
        <Section title={t('csi.positions')}><CsiChart option={positionOption(data, colors, unknown)} label={t('csi.positions')} /><Alternative label={t('csi.chartData')}><DataTable headers={[t('csi.position'), t('csi.complaints'), t('csi.employees'), t('csi.anonymous')]} rows={data.positions.map(row => [row.position ?? unknown, row.complaints, row.known_employees, row.anonymous_complaints])} /></Alternative></Section>
        <Section title={t('csi.tenure')}><p className="p-3 text-xs text-muted">{t('csi.roster', { time: data.tenure.as_of_sim })}</p><CsiChart option={tenureOption(data, colors, text)} label={t('csi.tenure')} /><Alternative label={t('csi.chartData')}><DataTable headers={[t('csi.groupLabel'), t('csi.employees'), 'min', 'Q1', 'median', 'Q3', 'max']} rows={data.tenure.groups.map(row => [t('csi.group.' + row.group), `${row.known_tenure}/${row.employees}`, ...[row.minimum, row.q1, row.median, row.q3, row.maximum].map(number)])} /></Alternative></Section>
        <Section title={t('csi.heatmap')}><RegionHeatmap items={data.heatmap} regions={regions.data ?? []} selected={scope.region_code} onSelect={code => update({ region_code: code === scope.region_code ? undefined : code, branch_id: undefined })} colors={colors} /></Section>
        <Section title={t('csi.top')}><CsiChart option={topOption(data, colors)} label={t('csi.top')} /><DataTable headers={[t('csi.branch'), t('csi.complaints'), t('csi.wait')]} rows={data.top_branches.map(row => [trace('branch', row.branch_id, row.branch_code), row.complaints, number(row.average_wait_min)])} /></Section>
      </div>
      <Section title={t('csi.sample')}><div className="space-y-2 p-3 text-sm"><Badge tone="info">{data.probabilities.synthetic === true ? t('csi.synthetic') : data.probabilities.synthetic === false ? t('csi.observed') : t('csi.sourceUnknown')}</Badge><p>{t('csi.sampleSize', { complaints: number(data.probabilities.sample_complaints), visits: number(data.probabilities.sample_visits), cohorts: data.probabilities.complete_cohorts })}</p><p className="text-muted">{t('csi.sampleNote')}</p><p>{t('csi.exclusions', { incomplete: data.probabilities.incomplete_cohorts, partial: data.probabilities.partial_window_cohorts })}</p></div></Section>
      <div className="grid min-w-0 gap-4 xl:grid-cols-2">{probability('wait')}{probability('redirects')}</div>
    </>}
  </main>
}
