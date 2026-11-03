import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import type { EChartsOption } from 'echarts'
import { useRefs } from '@/shared/api/hooks'
import { Badge, Section } from '@/shared/ui'
import { RUSSIA, MAP_WIDTH, MAP_HEIGHT, russiaProjection } from '@/shared/geo/russia'
import { CsiChart } from '@/pages/csi/Chart'
import { useCsiPalette } from '@/pages/csi/palette'
import type { BranchAnalytics as Data } from './api'

export function BranchAnalytics({ data, runId, region, onRegion, offset, onOffset }: { data: Data; runId: string; region: string | null; onRegion: (code: string | null) => void; offset: number; onOffset: (offset: number) => void }) {
  const { t, i18n } = useTranslation()
  const refs = useRefs('regions')
  const colors = useCsiPalette()
  const { path } = useMemo(() => russiaProjection(), [])
  const number = (value: number | null | undefined) => value == null ? t('branchMap.unknown') : new Intl.NumberFormat(i18n.language, { maximumFractionDigits: 2 }).format(value)
  const names = new Map((refs.data ?? []).map(row => [row.code, i18n.language.startsWith('en') ? row.name_en ?? row.name_ru : row.name_ru]))
  const byCode = new Map(data.pressure.map(row => [row.region_code, row]))
  const known = data.pressure.flatMap(row => row.signals_per_open_branch == null ? [] : [row.signals_per_open_branch])
  const max = Math.max(0, ...known)
  const option: EChartsOption = useMemo(() => ({
    animation: false, aria: { enabled: true }, tooltip: { trigger: 'axis', renderMode: 'richText', confine: true },
    textStyle: { color: colors.ink }, legend: { textStyle: { color: colors.muted } },
    grid: { left: 16, right: 16, top: 42, bottom: 30, containLabel: true },
    xAxis: { type: 'category', data: data.network.items.map(row => row.month.slice(0, 7)), axisLabel: { color: colors.muted } },
    yAxis: { type: 'value', min: 0, minInterval: 1, splitLine: { lineStyle: { color: colors.line } } },
    series: [
      { type: 'line', name: t('branchMap.openOffices'), data: data.network.items.map(row => row.open_count), connectNulls: false, itemStyle: { color: colors.brand } },
      { type: 'line', name: t('branchMap.closedOffices'), data: data.network.items.map(row => row.closed_count), connectNulls: false, itemStyle: { color: colors.muted }, lineStyle: { type: 'dashed' } },
    ],
  }), [data.network, colors, t])
  const noCurrent = data.scope.run_ids?.length === 0
  return <div className="col-span-full grid min-w-0 gap-4 md:grid-cols-2" aria-label={t('branchMap.analytics')}>
    <h2 className="col-span-full text-lg font-semibold">{t('branchMap.analytics')}</h2>
    {noCurrent && <p className="col-span-full text-sm text-muted">{t('branchMap.noCurrent')}</p>}
    <Section title={t('branchMap.pressure')}>
      <p className="p-3 text-xs text-muted">{t('branchMap.pressureBasis')}</p>
      <svg viewBox={`0 0 ${MAP_WIDTH} ${MAP_HEIGHT}`} role="group" aria-label={t('branchMap.pressure')} className="block w-full">
        <defs><pattern id="branch-pressure-unknown" patternUnits="userSpaceOnUse" width={6} height={6}><path d="M0 6L6 0" stroke={colors.muted} strokeWidth={.5} /></pattern></defs>
        {RUSSIA.features.map(feature => {
          const code = feature.properties.code, value = noCurrent ? null : byCode.get(code)?.signals_per_open_branch
          const label = `${names.get(code) ?? feature.properties.name}: ${number(value)}`
          const select = () => onRegion(region === code ? null : code)
          return <path key={code} d={path(feature) ?? ''} fill={value == null ? 'url(#branch-pressure-unknown)' : colors.brand} opacity={value == null ? .4 : max > 0 ? .12 + .88 * value / max : .12} stroke={region === code ? colors.ink : colors.line} strokeWidth={region === code ? 2 : .5} role="button" tabIndex={0} aria-label={label} aria-pressed={region === code} className="cursor-pointer focus-visible:stroke-[3]" onClick={select} onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); select() } }}><title>{label}</title></path>
        })}
      </svg>
      <div className="max-h-48 overflow-auto p-3"><table className="w-full text-left text-xs"><thead><tr><th>{t('branchMap.region')}</th><th>{t('branchMap.pressure')}</th></tr></thead><tbody>{data.pressure.map(row => <tr key={row.region_code ?? 'unknown'}><td><button className="text-brand hover:underline" onClick={() => onRegion(row.region_code)}>{names.get(row.region_code ?? '') ?? row.region_code ?? t('branchMap.unknown')}</button></td><td>{number(noCurrent ? null : row.signals_per_open_branch)}</td></tr>)}</tbody></table></div>
    </Section>
    <Section title={t('branchMap.deficit')}>
      <p className="p-3 text-xs text-muted">{data.deficit_threshold == null ? t('branchMap.thresholdUnknown') : t('branchMap.deficitBasis', { value: number(data.deficit_threshold) })}</p>
      <ul className="space-y-2 p-3">{!noCurrent && data.pressure.filter(row => row.deficit === true).map(row => <li key={row.region_code ?? 'unknown'}><button className="text-brand hover:underline" onClick={() => onRegion(row.region_code)}>{names.get(row.region_code ?? '') ?? row.region_code ?? t('branchMap.unknown')}</button> <Badge>{number(row.signals_per_open_branch)}</Badge></li>)}</ul>
      {!noCurrent && data.deficit_threshold != null && data.pressure.every(row => row.deficit === false) && <p className="p-3 text-sm text-muted">{t('branchMap.noDeficit')}</p>}
      {data.pressure.some(row => row.deficit == null) && <p className="p-3 text-xs text-muted">{t('branchMap.unknownDeficit')}</p>}
    </Section>
    <Section title={t('branchMap.network')}>
      <p className="p-3 text-xs text-muted">{t('branchMap.networkBasis.' + data.network.basis)} {data.network.synthetic === true && t('branchMap.synthetic')}</p>
      <CsiChart option={option} label={t('branchMap.network')} />
      <div className="max-h-36 overflow-auto px-3 pb-3"><table className="w-full text-left text-xs"><thead><tr><th>{t('branchMap.month')}</th><th>{t('branchMap.openOffices')}</th><th>{t('branchMap.closedOffices')}</th></tr></thead><tbody>{data.network.items.map(row => <tr key={row.month}><td>{row.month.slice(0, 7)}</td><td>{number(row.open_count)}</td><td>{number(row.closed_count)}</td></tr>)}</tbody></table></div>
    </Section>
    <Section title={t('branchMap.closureZones')} right={region && <button className="btn btn-sm" onClick={() => onRegion(null)}>{t('branchMap.clearRegion')}</button>}>
      <p className="p-3 text-xs text-muted">{t('branchMap.zoneBasis')}</p>
      <div className="max-h-72 overflow-auto p-3"><table className="w-full text-left text-xs"><thead><tr><th>{t('branchMap.office')}</th><th>{t('branchMap.closedDate')}</th><th>{t('branchMap.zoneSignals')}</th></tr></thead><tbody>{data.closure_zones.items.map(row => <tr key={row.branch_id}><td><Link className="text-brand hover:underline" to={`/trace/branch/${encodeURIComponent(String(row.branch_id))}?run_id=${encodeURIComponent(runId)}`}>{row.branch_code}</Link></td><td>{new Date(row.closed_sim).toLocaleDateString(i18n.language, { timeZone: 'Europe/Moscow' })}</td><td>{number(noCurrent ? null : row.signals)}</td></tr>)}</tbody></table></div>
      <div className="flex gap-2 p-3"><button className="btn btn-sm" disabled={offset === 0} onClick={() => onOffset(Math.max(0, offset - 50))}>{t('csi.previous')}</button><button className="btn btn-sm" disabled={data.closure_zones.next_offset == null} onClick={() => onOffset(data.closure_zones.next_offset!)}>{t('csi.next')}</button></div>
    </Section>
  </div>
}
