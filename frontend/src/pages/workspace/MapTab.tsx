import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { RUSSIA, MAP_WIDTH as W, MAP_HEIGHT as H, russiaProjection } from '@/shared/geo/russia'
import { clsx } from 'clsx'
import { useMapCities, useMapHeat, useMapZones, type MapLayer } from '@/shared/api/hooks'
import type { MapZone, RegionHeat } from '@/shared/api/client'
import { Badge, Empty, ErrorBox, KV, Section, Skeleton } from '@/shared/ui'

type Mode = 'heat' | 'zones'
const LAYERS: MapLayer[] = ['signals', 'critical', 'incidents', 'churn']
const WINDOWS = [24, 24 * 7, 24 * 30]

function heatColor(intensity: number): string {
  if (intensity <= 0) return 'var(--map-empty, #e9edf2)'
  const a = 0.18 + 0.82 * Math.min(1, intensity)
  return `rgba(214, 69, 65, ${a.toFixed(3)})`
}
const ZONE_FILL: Record<string, string> = { green: '#8fcf9a', yellow: '#f2c94c', red: '#e2574c' }

export function MapTab() {
  const { t } = useTranslation()
  const [mode, setMode] = useState<Mode>('heat')
  const [layer, setLayer] = useState<MapLayer>('signals')
  const [win, setWin] = useState(24 * 7)
  const [runScope, setRunScope] = useState<'current' | 'all'>('all')
  const [selected, setSelected] = useState<string | null>(null)
  const geo = RUSSIA

  const heat = useMapHeat(layer, win, runScope)
  const zones = useMapZones(runScope)
  const cities = useMapCities(selected, win, runScope)

  const { projection, path } = useMemo(() => russiaProjection(
    (heat.data ?? []).flatMap((r): [number, number][] => r.lon != null && r.lat != null ? [[r.lon, r.lat]] : []),
  ), [heat.data])

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

  return (
    <div className="grid h-full items-start gap-4 overflow-auto p-3 xl:grid-cols-[minmax(0,1fr)_20rem]">
      <Section
        title={t('map.title')}
        className="min-w-0"
        right={
          <div className="flex flex-wrap items-center gap-1 text-xs">
            <Seg value={mode} onChange={setMode} items={[{ id: 'heat', label: t('map.mode.heat') }, { id: 'zones', label: t('map.mode.zones') }]} />
            {mode === 'heat' && <Seg value={layer} onChange={setLayer} items={LAYERS.map((l) => ({ id: l, label: t(`map.layer.${l}`) }))} />}
            {mode === 'heat' && <Seg value={String(win)} onChange={(v) => setWin(Number(v))} items={WINDOWS.map((w) => ({ id: String(w), label: t(`map.window.${w}`) }))} />}
            <Seg value={runScope} onChange={setRunScope} items={[{ id: 'current', label: t('map.scope.current') }, { id: 'all', label: t('map.scope.all') }]} />
          </div>
        }
      >
        {heat.error && <ErrorBox error={heat.error} compact />}
        {(
          <div>
            <svg viewBox={`0 0 ${W} ${H}`} className="block h-[clamp(14rem,calc(100dvh-25rem),42rem)] w-full" preserveAspectRatio="xMidYMid meet" role="img" aria-label={t('map.title')}>
              <rect width={W} height={H} fill="transparent" onClick={() => setSelected(null)} />
              {geo.features.map((f) => {
                const code = f.properties.code
                const r = byCode.get(code)
                const z = zoneBy.get(code)
                const fill = mode === 'heat' ? heatColor(r?.intensity ?? 0) : ZONE_FILL[z?.zone ?? 'green']
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
            </svg>
            <div className="flex flex-wrap items-center gap-2 border-t border-line px-3 py-2 text-xs text-muted">
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
    </div>
  )
}

function fmtVal(layer: MapLayer, v: number | undefined): string {
  if (v == null) return '—'
  return layer === 'churn' ? v.toFixed(0) : String(Math.round(v))
}

function labelFor(mode: Mode, layer: MapLayer, r: RegionHeat | undefined, z: MapZone | undefined, t: (k: string) => string): string {
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
