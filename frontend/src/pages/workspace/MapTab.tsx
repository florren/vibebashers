import { useSearchParams } from 'react-router-dom'
import { useEffect, useId, useMemo, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { RUSSIA, MAP_WIDTH as W, MAP_HEIGHT as H, russiaProjection } from '@/shared/geo/russia'
import { clsx } from 'clsx'
import { useMapCities, useMapHeat, useMapZones, type MapLayer } from '@/shared/api/hooks'
import type { MapZone, RegionHeat } from '@/shared/api/client'
import { Badge, Empty, ErrorBox, KV, Section, Skeleton } from '@/shared/ui'
import { useViewPreset } from '@/shared/layout/preset'
import { useWs } from '@/shared/ws/client'
import { useBranchDirectory, useDirectionCatalog } from '@/pages/csi/api'
import { branchAnalyticsOptions, branchDetailOptions, closedDetailsOptions, directSignalCount, type BranchScope } from './map/api'
import { clusterBranches, coordinate, projectBranches, BRANCH_STYLE, type BranchCluster } from './map/branches'
import { BranchLayer } from './map/BranchLayer'
import { BranchCard } from './map/BranchCard'
import { BranchAnalytics } from './map/BranchAnalytics'

type Mode = 'heat' | 'zones'
const LAYERS: MapLayer[] = ['signals', 'critical', 'incidents', 'churn']
const WINDOWS = [24, 24 * 7, 24 * 30]

function heatColor(intensity: number): string {
  if (intensity <= 0) return 'var(--map-empty, #e9edf2)'
  const a = 0.18 + 0.82 * Math.min(1, intensity)
  return `rgba(214, 69, 65, ${a.toFixed(3)})`
}
const ZONE_FILL: Record<string, string> = { green: '#8fcf9a', yellow: '#f2c94c', red: '#e2574c' }

export function MapTab({ runScope: externalScope, onRunScopeChange }: { runScope?: string; onRunScopeChange?: (value: string) => void }) {
  const { t, i18n } = useTranslation()
  const [params, setParams] = useSearchParams()
  const mode: Mode = params.get('map_mode') === 'zones' ? 'zones' : 'heat'
  const setMode = (mode: Mode) => setParams(p => { if (mode === 'zones') p.set('map_mode', mode); else p.delete('map_mode'); return p }, { replace: true })
  const [layer, setLayer] = useState<MapLayer>('signals')
  const [win, setWin] = useState(24 * 7)
  const runScope = externalScope ?? params.get('run_id') ?? 'current'
  const setRunScope = (value: string) => { if (externalScope !== undefined && onRunScopeChange) onRunScopeChange(value); else setParams(previous => { previous.set('run_id', value); return previous }, { replace: true }) }
  const [branchesOn, setBranchesOn] = useState(false)
  const [binding, setBinding] = useState(() => localStorage.getItem('cx.ui.productLine') ?? '')
  const [selectedBranch, setSelectedBranch] = useState<string | null>(null)
  const [selectionScope, setSelectionScope] = useState('')
  const [selectedCluster, setSelectedCluster] = useState<BranchCluster | null>(null)
  const [offset, setOffset] = useState(0)
  const [zoom, setZoom] = useState({ scale: 1, centerX: W / 2, centerY: H / 2 })
  const [size, setSize] = useState({ width: 0, height: 0 })
  const mapRef = useRef<SVGSVGElement>(null)
  const clip = 'workspace-map-' + useId().replace(/:/g, '')
  const role = useViewPreset(state => state.role)
  const cache = useQueryClient()
  const [selected, setSelected] = useState<string | null>(null)
  const geo = RUSSIA
  const scope: BranchScope = { run_id: runScope, period: win === 24 ? 'day' : win === 168 ? 'week' : 'month', ...(selected ? { region_code: selected } : {}), ...(params.has('product_line') ? { product_line: params.get('product_line')! } : {}) }
  const headers = useMemo(() => ({ 'X-Cx-Role': role, ...(binding && role === 'product_manager' ? { 'X-Cx-Product-Line': binding } : {}) }), [role, binding])
  const scopeKey = JSON.stringify([scope, headers])
  const currentBranch = selectionScope === scopeKey ? selectedBranch : null
  const currentCluster = selectionScope === scopeKey ? selectedCluster : null
  const directory = useBranchDirectory({ product_line: scope.product_line, region_code: scope.region_code }, headers, branchesOn)
  const catalog = useDirectionCatalog(headers, branchesOn)
  const branches = useMemo(() => branchesOn && !directory.isError ? directory.data?.pages.flatMap(page => page.items) ?? [] : [], [branchesOn, directory.data, directory.isError])
  const closedCodes = useMemo(() => branches.filter(branch => branch.branch_status === 'closed').map(branch => branch.code).sort(), [branches])
  const closed = useQuery({ ...closedDetailsOptions(closedCodes, scope, headers), enabled: branchesOn && directory.data != null && !directory.hasNextPage && closedCodes.length > 0 })
  const detail = useQuery({ ...branchDetailOptions(currentBranch, scope, headers), enabled: branchesOn && currentBranch != null })
  const analytics = useQuery({ ...branchAnalyticsOptions(scope, headers, offset), enabled: branchesOn })
  useEffect(() => { setSelectedBranch(null); setSelectedCluster(null); setOffset(0) }, [scopeKey])
  const { hasNextPage, isFetchingNextPage, isError: isDirectoryError, fetchNextPage } = directory
  useEffect(() => { if (branchesOn && hasNextPage && !isFetchingNextPage && !isDirectoryError) void fetchNextPage() }, [branchesOn, hasNextPage, isFetchingNextPage, isDirectoryError, fetchNextPage])
  useEffect(() => {
    const element = mapRef.current
    if (!element) return
    const update = () => { const bounds = element.getBoundingClientRect(); setSize({ width: bounds.width, height: bounds.height }) }
    update()
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(update)
    observer?.observe(element); window.addEventListener('resize', update)
    return () => { observer?.disconnect(); window.removeEventListener('resize', update) }
  }, [])
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined
    const unsubscribe = useWs.subscribe((state, previous) => {
      if (state.events === previous.events) return
      const topic = state.events[0]?.topic
      if (topic === 'runs' || topic === 'settings') {
        void cache.resetQueries({ queryKey: ['map'] }); void cache.resetQueries({ queryKey: ['csi', 'directory'] }); return
      }
      if (['signals', 'incidents', 'metrics', 'compliance'].includes(topic ?? '') && !timer) timer = setTimeout(() => { timer = undefined; void cache.invalidateQueries({ queryKey: ['map', 'branches'] }) }, 500)
    })
    return () => { unsubscribe(); clearTimeout(timer) }
  }, [cache])

  const heat = useMapHeat(layer, win, runScope)
  const zones = useMapZones(runScope)
  const cities = useMapCities(selected, win, runScope)

  const { projection, path } = useMemo(() => russiaProjection(
    [...(heat.data ?? []).flatMap((r): [number, number][] => r.lon != null && r.lat != null ? [[r.lon, r.lat]] : []), ...branches.flatMap(branch => { const lat = coordinate(branch.lat, 90), lon = coordinate(branch.lon, 180); return lat != null && lon != null ? [[lon, lat] as [number, number]] : [] })],
  ), [heat.data, branches])
  const projected = useMemo(() => projectBranches(branches, projection), [branches, projection])
  const viewport = { scale: zoom.scale, x: W / 2 - zoom.centerX * zoom.scale, y: H / 2 - zoom.centerY * zoom.scale, ...size }
  const clusters = size.width > 0 && size.height > 0 ? clusterBranches(projected.points, viewport, 44) : []
  const selectCluster = (cluster: BranchCluster) => {
    setSelectionScope(scopeKey)
    if (cluster.items.length === 1) { setSelectedBranch(cluster.anchor.branch.code); setSelectedCluster(null) }
    else {
      setSelectedCluster(cluster); setSelectedBranch(null)
      if (zoom.scale < 8) setZoom({ scale: Math.min(8, zoom.scale * 2), centerX: (Math.min(...cluster.items.map(p => p.x)) + Math.max(...cluster.items.map(p => p.x))) / 2, centerY: (Math.min(...cluster.items.map(p => p.y)) + Math.max(...cluster.items.map(p => p.y))) / 2 })
    }
  }

  const byCode = useMemo(() => new Map((heat.data ?? []).map((r) => [r.region_code ?? '', r])), [heat.data])
  const zoneBy = useMemo(() => new Map((zones.data?.items ?? []).map((z) => [z.region_code ?? '', z])), [zones.data])
  const polygons = useMemo(() => new Set((geo?.features ?? []).map((f) => f.properties.code)), [geo])
  const top = useMemo(() => [...(heat.data ?? [])].filter((r) => (r.value ?? 0) > 0).sort((a, b) => (b.value ?? 0) - (a.value ?? 0)).slice(0, 8), [heat.data])
  const zoneCounts = useMemo(() => {
    const c = { green: 0, yellow: 0, red: 0 }
    for (const z of zones.data?.items ?? []) if (z.zone && z.zone in c) c[z.zone as keyof typeof c] += 1
    return c
  }, [zones.data])

  const sel = selected ? byCode.get(selected) : undefined
  const selZone = selected ? zoneBy.get(selected) : undefined

  // Карта занимает доступную строку целиком; боковая панель на узком экране прокручивается ниже.
  return (
    <div className="map-layout grid h-full min-h-0 auto-rows-[100%] items-start gap-4 overflow-auto p-3 xl:grid-cols-[minmax(0,1fr)_20rem]">
      <Section
        title={t('map.title')}
        className="map-panel flex h-full min-h-0 min-w-0 flex-col [&>header]:shrink-0 [&>div]:flex [&>div]:min-h-0 [&>div]:flex-1 [&>div]:flex-col"
        right={
          <div className="flex flex-wrap items-center gap-1 text-xs">
            <Seg value={mode} onChange={setMode} items={[{ id: 'heat', label: t('map.mode.heat') }, { id: 'zones', label: t('map.mode.zones') }]} />
            {mode === 'heat' && <Seg value={layer} onChange={setLayer} items={LAYERS.map((l) => ({ id: l, label: t(`map.layer.${l}`) }))} />}
            {mode === 'heat' && <Seg value={String(win)} onChange={(v) => setWin(Number(v))} items={WINDOWS.map((w) => ({ id: String(w), label: t(`map.window.${w}`) }))} />}
            <button className="btn btn-sm" aria-pressed={branchesOn} onClick={() => setBranchesOn(value => !value)}>{t('branchMap.toggle')}</button>
            {(branchesOn || zoom.scale > 1) && <><button className="btn btn-sm" aria-label={t('branchMap.zoomIn')} disabled={zoom.scale >= 8} onClick={() => setZoom(value => ({ ...value, scale: Math.min(8, value.scale * 2) }))}>+</button><button className="btn btn-sm" aria-label={t('branchMap.zoomOut')} disabled={zoom.scale === 1} onClick={() => setZoom(value => ({ ...value, scale: Math.max(1, value.scale / 2) }))}>−</button><button className="btn btn-sm" onClick={() => setZoom({ scale: 1, centerX: W / 2, centerY: H / 2 })}>{t('branchMap.resetZoom')}</button></>}
            {!['current', 'all'].includes(params.get('run_id') ?? runScope) && <span>{t('branchMap.explicitRun', { id: runScope || t('branchMap.unknown') })}</span>}
            <Seg value={params.get('run_id') ?? runScope} onChange={setRunScope} items={[{ id: 'current', label: t('map.scope.current') }, { id: 'all', label: t('map.scope.all') }]} />
          </div>
        }
      >
        {heat.error && <ErrorBox error={heat.error} compact />}
        {zones.error && <ErrorBox error={zones.error} compact />}
        {branchesOn && <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-line p-2 text-xs">
          <label>{t('branchMap.direction')} <select className="input" value={scope.product_line ?? ''} onChange={event => setParams(previous => { if (event.target.value) previous.set('product_line', event.target.value); else previous.delete('product_line'); return previous })}><option value="">{t('csi.all')}</option>{catalog.data?.map(line => <option key={line.code} value={line.code}>{i18n.language.startsWith('en') ? line.name_en : line.name_ru}</option>)}</select></label>
          {role === 'product_manager' && <label>{t('csi.binding')} <input className="input" value={binding} onChange={event => { localStorage.setItem('cx.ui.productLine', event.target.value); setBinding(event.target.value) }} /></label>}
          <span>{directory.isError ? t('branchMap.directoryUnavailable') : directory.isPending ? t('common.loading') : t('branchMap.loaded', { count: branches.length })}{!directory.isError && directory.hasNextPage ? ' · ' + t('common.loading') : ''}</span>
          {directory.data?.pages[0] && <Badge>{t('branchMap.directoryMode.' + (directory.data.pages[0].directory.mode ?? 'unknown'))}</Badge>}
          {projected.unlocated.length > 0 && <span>{t('branchMap.unlocated', { count: projected.unlocated.length })}</span>}
          {Object.values(closed.data ?? {}).some(value => value.error != null) && <span role="status">{t('branchMap.countsUnknown')}</span>}
        </div>}
        {branchesOn && (directory.error || catalog.error) && <ErrorBox error={directory.error ?? catalog.error} compact />}
        {(
          <div className="flex min-h-0 flex-1 flex-col">
            <svg ref={mapRef} viewBox={`0 0 ${W} ${H}`} className="map-canvas block min-h-0 w-full flex-1" preserveAspectRatio="xMidYMid meet" role="img" aria-label={t('map.title')}>
              <rect width={W} height={H} fill="transparent" onClick={() => setSelected(null)} />
              <defs><clipPath id={clip}><rect width={W} height={H} /></clipPath></defs>
              <g clipPath={`url(#${clip})`}><g className="transition-transform duration-[400ms] motion-reduce:transition-none" transform={`translate(${viewport.x} ${viewport.y}) scale(${zoom.scale})`}>
              {geo.features.map((f) => {
                const code = f.properties.code
                const r = byCode.get(code)
                const z = zoneBy.get(code)
                const fill = mode === 'heat' ? heatColor(r?.intensity ?? 0) : z?.zone ? ZONE_FILL[z.zone] : 'var(--map-empty, #e9edf2)'
                const d = path(f)
                if (!d) return null
                return (
                  <path
                    key={code}
                    d={d}
                    fill={fill}
                    stroke={selected === code ? '#1d4ed8' : '#ffffff'}
                    strokeWidth={selected === code ? 1.8 : 0.5}
                    className="cursor-pointer transition-[fill] duration-300 hover:opacity-80"
                    onClick={() => setSelected(code === selected ? null : code)}
                  >
                    <title>{`${r?.name_ru ?? f.properties.name}: ${labelFor(mode, layer, r, z, t)}`}</title>
                  </path>
                )
              })}
              {branchesOn && size.width > 0 && size.height > 0 && <BranchLayer clusters={clusters} pixelRatio={Math.min(size.width / W, size.height / H)} zoom={zoom.scale} offsetX={viewport.x} closed={closed.data} selected={currentBranch} onSelect={selectCluster} />}
              <g data-testid="signal-layer">
              {(heat.data ?? [])
                .filter((r) => !polygons.has(r.region_code ?? '') && r.lat != null && r.lon != null)
                .map((r) => {
                  const p = projection([r.lon as number, r.lat as number])
                  if (!p) return null
                  const z = zoneBy.get(r.region_code ?? '')
                  const fill = mode === 'heat' ? heatColor(r.intensity ?? 0) : ZONE_FILL[z?.zone ?? 'green']
                  return (
                    <circle key={r.region_code} cx={p[0]} cy={p[1]} r={6} fill={fill} stroke="#fff" strokeWidth={0.8} className="cursor-pointer" onClick={() => setSelected(r.region_code ?? null)}>
                      <title>{`${r.name_ru}: ${labelFor(mode, layer, r, z, t)}`}</title>
                    </circle>
                  )
                })}
              {(heat.data ?? [])
                .filter((r) => (r.value ?? 0) > 0 && r.lat != null && r.lon != null && (mode === 'heat' ? (r.intensity ?? 0) >= 0.5 : zoneBy.get(r.region_code ?? '')?.zone === 'red'))
                .map((r) => {
                  const p = projection([r.lon as number, r.lat as number])
                  if (!p) return null
                  return (
                    <text key={`l-${r.region_code}`} x={p[0]} y={p[1]} textAnchor="middle" fontSize={10} fontWeight={600} fill="#1f2937" pointerEvents="none">
                      {mode === 'heat' ? fmtVal(layer, r.value) : (zoneBy.get(r.region_code ?? '')?.critical_count || '')}
                    </text>
                  )
                })}
              </g></g></g>
            </svg>
            <div className="flex shrink-0 flex-wrap items-center gap-2 border-t border-line px-3 py-2 text-xs text-muted">
              {branchesOn && <span className="flex flex-wrap gap-2" aria-label={t('branchMap.legend')}>{Object.entries(BRANCH_STYLE).map(([type, style]) => <span className="inline-flex items-center gap-1" key={type}><span className="inline-block h-2.5 w-2.5 rounded-full border-2" style={{ borderColor: style.color, borderStyle: style.dash ? 'dashed' : 'solid', backgroundColor: type === 'mobile' ? 'transparent' : style.color }} />{t('branchMap.type.' + type)}</span>)}</span>}
              {mode === 'heat' ? (
                <>
                  <span>{t('map.legend.low')}</span>
                  <span className="h-2 w-24 rounded" style={{ background: 'linear-gradient(90deg, rgba(214,69,65,0.18), rgba(214,69,65,1))' }} />
                  <span>{t('map.legend.high')}</span>
                </>
              ) : (
                <>
                  {(['green', 'yellow', 'red'] as const).map((z) => (
                    <span key={z} className="flex items-center gap-1">
                      <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: ZONE_FILL[z] }} />
                      {t(`map.zone.${z}`)} · {zoneCounts[z]}
                    </span>
                  ))}
                  <span>· {t('map.noGeo', { n: zones.data?.no_geo_count ?? 0 })}</span>
                </>
              )}
            </div>
          </div>
        )}
      </Section>

      <div className="flex flex-col gap-3">
        {branchesOn && currentBranch && <BranchCard data={detail.error ? undefined : detail.data} error={detail.error} loading={detail.isPending} runId={runScope} close={() => setSelectedBranch(null)} />}
        {branchesOn && currentCluster && <Section title={t('branchMap.cluster', { count: currentCluster.items.length })}><ul className="max-h-60 overflow-auto p-3">{currentCluster.items.map(point => <li key={point.branch.code}><button className="text-sm text-brand hover:underline" onClick={() => { setSelectionScope(scopeKey); setSelectedBranch(point.branch.code) }}>{point.branch.code} · {t('branchMap.status.' + (point.branch.branch_status ?? 'unknown'))}{point.branch.branch_status === 'closed' ? ' · ' + (directSignalCount(closed.data?.[point.branch.code]) == null ? t('branchMap.closedUnknown') : t('branchMap.closedSignals', { count: directSignalCount(closed.data?.[point.branch.code])! })) : ''}</button></li>)}</ul></Section>}
        {sel ? (
          <Section title={sel.name_ru ?? selected ?? ''} right={<button className="btn btn-sm" onClick={() => setSelected(null)}>{t('common.close')}</button>}>
            <div className="divide-y divide-line">
              <KV k={t('map.layer.signals')} v={sel.signals ?? 0} />
              <KV k={t('map.layer.critical')} v={sel.critical ?? 0} />
              <KV k={t('map.layer.incidents')} v={sel.incidents_open ?? 0} />
              <KV k={t('map.layer.churn')} v={`${Math.round(sel.churn_risk_avg ?? 0)}`} />
              {selZone && (
                <KV
                  k={t('map.mode.zones')}
                  v={
                    <span className="flex items-center gap-2">
                      <Badge tone={selZone.zone === 'red' ? 'danger' : selZone.zone === 'yellow' ? 'warn' : 'ok'}>{t(`map.zone.${selZone.zone ?? 'green'}`)}</Badge>
                      <span className="num text-xs text-muted">
                        {t('map.negativity')} {Math.round((selZone.negativity_index ?? 0) * 100)}% · copilot {Math.round((selZone.copilot_index ?? 0) * 100)}%
                      </span>
                    </span>
                  }
                />
              )}
            </div>
            <div className="border-t border-line px-3 py-2 text-xs font-semibold uppercase tracking-wide text-muted">{t('map.cities')}</div>
            {cities.isLoading && <Skeleton className="m-3 h-16" />}
            {cities.data && cities.data.filter((c) => (c.signals ?? 0) > 0).length === 0 && <div className="px-3 pb-3 text-xs text-muted">{t('map.noCitySignals')}</div>}
            <ul className="max-h-72 divide-y divide-line overflow-auto">
              {(cities.data ?? [])
                .filter((c) => (c.signals ?? 0) > 0)
                .map((c) => (
                  <li key={c.city_id} className="flex items-center justify-between px-3 py-1.5 text-sm">
                    <span className="truncate">{c.name_ru}</span>
                    <span className="num flex items-center gap-2 text-xs">
                      <span>{c.signals}</span>
                      {(c.critical ?? 0) > 0 && <Badge tone="danger">{c.critical}</Badge>}
                    </span>
                  </li>
                ))}
            </ul>
          </Section>
        ) : (
          <Section title={t('map.top')}>
            {heat.isLoading && <Skeleton className="m-3 h-24" />}
            {top.length === 0 && !heat.isLoading && <Empty title={t('map.empty')} hint={t('map.emptyHint')} />}
            <ul className="divide-y divide-line">
              {top.map((r) => (
                <li key={r.region_code} className={clsx('flex cursor-pointer items-center justify-between px-3 py-1.5 text-sm hover:bg-raised')} onClick={() => setSelected(r.region_code ?? null)}>
                  <span className="flex items-center gap-2 truncate">
                    <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: mode === 'heat' ? heatColor(r.intensity ?? 0) : ZONE_FILL[zoneBy.get(r.region_code ?? '')?.zone ?? 'green'] }} />
                    <span className="truncate">{r.name_ru}</span>
                  </span>
                  <span className="num text-xs">{fmtVal(layer, r.value)}</span>
                </li>
              ))}
            </ul>
          </Section>
        )}
        <Section title={t('map.how')}>
          <p className="px-3 py-2 text-xs leading-relaxed text-muted">{mode === 'heat' ? t('map.howHeat') : t('map.howZones', { yellow: Math.round((zones.data?.thresholds?.yellow ?? 0.25) * 100), red: Math.round((zones.data?.thresholds?.red ?? 0.5) * 100), crit: (zones.data?.thresholds as { critical_red?: number } | undefined)?.critical_red ?? 3 })}</p>
        </Section>
      </div>
      {branchesOn && analytics.error && <div className="col-span-full"><ErrorBox error={analytics.error} /></div>}
      {branchesOn && analytics.data && !analytics.error && <BranchAnalytics data={analytics.data} runId={runScope} region={selected} onRegion={setSelected} offset={offset} onOffset={setOffset} />}
    </div>
  )
}

function fmtVal(layer: MapLayer, v: number | undefined): string {
  if (v == null) return '—'
  return layer === 'churn' ? v.toFixed(0) : String(Math.round(v))
}

function labelFor(mode: Mode, layer: MapLayer, r: RegionHeat | undefined, z: MapZone | undefined, t: (k: string) => string): string {
  if (mode === 'zones' && !z) return t('branchMap.unknown')
  if (mode === 'zones') return `${t(`map.zone.${z?.zone ?? 'green'}`)} · ${t('map.layer.signals').toLowerCase()} ${z?.signals_total ?? 0}`
  return `${t(`map.layer.${layer}`).toLowerCase()} ${fmtVal(layer, r?.value)}`
}

function Seg<T extends string>({ value, onChange, items }: { value: T; onChange: (v: T) => void; items: { id: T; label: string }[] }) {
  return (
    <div className="flex overflow-hidden rounded border border-line">
      {items.map((it) => (
        <button key={it.id} type="button" className={clsx('px-2 py-0.5', value === it.id ? 'bg-brand-strong text-on-brand' : 'bg-surface text-muted hover:text-ink')} onClick={() => onChange(it.id)}>
          {it.label}
        </button>
      ))}
    </div>
  )
}
