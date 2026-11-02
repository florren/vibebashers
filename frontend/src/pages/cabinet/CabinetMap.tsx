import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { RUSSIA, MAP_WIDTH as W, MAP_HEIGHT as H, russiaProjection } from '@/shared/geo/russia'
import type { Overview } from './api'

const FILL = { green: '#8fcf9a', yellow: '#f2c94c', red: '#e2574c' }
/** Та же геометрия и проекция, что MapTab; данные только cabinet scope. */
export function CabinetMap({ regions, selected, onSelect, onPrefetch }: { regions: Overview['regions']; selected: string | null; onSelect: (code: string | null) => void; onPrefetch: (code: string) => void }) {
  const { t, i18n } = useTranslation()
  const { projection, path } = useMemo(() => russiaProjection(regions.flatMap(r => r.lat != null && r.lon != null ? [[r.lon, r.lat] as [number, number]] : [])), [regions])
  const byCode = useMemo(() => new Map(regions.map(r => [r.code, r])), [regions])
  const polygons = useMemo(() => new Set(RUSSIA.features.map(f => f.properties.code)), [])
  const selectedRegion = selected ? byCode.get(selected) : null
  const selectedFeature = RUSSIA.features.find(f => f.properties.code === selected)
  const center = selectedFeature ? path.centroid(selectedFeature) : selectedRegion?.lat != null && selectedRegion.lon != null ? projection([selectedRegion.lon, selectedRegion.lat]) : null
  const transform = center && Number.isFinite(center[0]) && Number.isFinite(center[1]) ? `translate(${W / 2 - center[0] * 1.8} ${H / 2 - center[1] * 1.8}) scale(1.8)` : 'translate(0 0) scale(1)'
  const label = (code: string) => { const row = byCode.get(code); return row ? `${i18n.language.startsWith('en') ? row.name_en : row.name_ru}: ${t(`map.zone.${row.zone}`)}, ${t('cabinet.signals')} ${row.signals}` : code }
  const events = (code: string) => ({
    onMouseEnter: () => onPrefetch(code), onFocus: () => onPrefetch(code),
    onClick: () => onSelect(selected === code ? null : code),
    onKeyDown: (event: React.KeyboardEvent<SVGElement>) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onSelect(selected === code ? null : code) } },
    role: 'button' as const, tabIndex: 0, 'aria-label': label(code), 'aria-pressed': selected === code,
  })
  return <div className="min-w-0 overflow-hidden rounded border border-line">
    <svg viewBox={`0 0 ${W} ${H}`} className="block max-h-[420px] w-full" role="group" aria-label={t('cabinet.map')} onKeyDown={e => { if (e.key === 'Escape') onSelect(null) }}>
      <defs><clipPath id="cabinet-map-clip"><rect width={W} height={H} /></clipPath></defs>
      <rect width={W} height={H} fill="transparent" onClick={() => onSelect(null)} />
      <g clipPath="url(#cabinet-map-clip)"><g transform={transform} className="transition-transform duration-[400ms] motion-reduce:transition-none">
        {RUSSIA.features.map(feature => { const code = feature.properties.code; const row = byCode.get(code); return <path key={code} d={path(feature) ?? ''} fill={FILL[row?.zone ?? 'green']} opacity={selected && selected !== code ? .35 : 1} stroke={selected === code ? 'var(--focus-ring, #1d4ed8)' : '#fff'} strokeWidth={selected === code ? 2 : .5} className="cursor-pointer transition-opacity duration-[400ms] motion-reduce:transition-none focus-visible:stroke-[3] focus-visible:stroke-brand" {...events(code)}><title>{label(code)}</title></path> })}
        {regions.filter(r => !polygons.has(r.code) && r.lat != null && r.lon != null).map(row => { const point = projection([row.lon!, row.lat!]); return point ? <circle key={row.code} cx={point[0]} cy={point[1]} r={6} fill={FILL[row.zone]} opacity={selected && selected !== row.code ? .35 : 1} stroke="#fff" className="cursor-pointer transition-opacity duration-[400ms] motion-reduce:transition-none focus-visible:stroke-[3] focus-visible:stroke-brand" {...events(row.code)}><title>{label(row.code)}</title></circle> : null })}
      </g></g>
    </svg>
    <div className="flex flex-wrap gap-3 border-t border-line px-3 py-2 text-sm" aria-label={t('cabinet.legend')}>{(['green', 'yellow', 'red'] as const).map(zone => <span className="flex items-center gap-1" key={zone}><span className="inline-block h-3 w-3 rounded-sm border border-line" style={{ backgroundColor: FILL[zone] }} />{t(`map.zone.${zone}`)}</span>)}</div>
  </div>
}
