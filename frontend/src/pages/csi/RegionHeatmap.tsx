import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { RUSSIA, MAP_WIDTH, MAP_HEIGHT, russiaProjection } from '@/shared/geo/russia'
import type { RefRow } from '@/shared/api/hooks'
import type { CsiAnalytics } from './api'
import type { CsiPalette } from './palette'

export function RegionHeatmap({ items, regions, selected, onSelect, colors }: { items: CsiAnalytics['heatmap']; regions: RefRow[]; selected?: string; onSelect: (code: string) => void; colors: CsiPalette }) {
  const { t, i18n } = useTranslation()
  const { path } = useMemo(() => russiaProjection(), [])
  const byCode = new Map(items.map(row => [row.region_code, row.complaints]))
  const names = new Map(regions.map(row => [row.code, i18n.language.startsWith('en') ? row.name_en ?? row.name_ru : row.name_ru]))
  const max = Math.max(0, ...items.map(row => row.complaints))
  const knownPolygons = new Set(RUSSIA.features.map(row => row.properties.code))
  const unplaced = items.filter(row => row.region_code == null || !knownPolygons.has(row.region_code))
  return <>
    <svg viewBox={`0 0 ${MAP_WIDTH} ${MAP_HEIGHT}`} className="block w-full" role="group" aria-label={t('csi.heatmap')}>
      {RUSSIA.features.map(feature => {
        const code = feature.properties.code, count = byCode.get(code) ?? 0
        const name = names.get(code) ?? feature.properties.name
        const geometry = path(feature)
        if (!geometry) return null
        return <path key={code} d={geometry} fill={count ? colors.danger : colors.line} fillOpacity={count && max ? 0.25 + 0.75 * count / max : 0.6} stroke={selected === code ? colors.ink : colors.surface} strokeWidth={selected === code ? 2 : 0.65} role="button" tabIndex={0} aria-pressed={selected === code} aria-label={t('csi.regionCount', { name, count })} onClick={() => onSelect(code)} onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onSelect(code) } }}>
          <title>{t('csi.regionCount', { name, count })}</title>
        </path>
      })}
    </svg>
    {unplaced.length > 0 && <p className="px-3 text-xs text-muted">{t('csi.unplaced', { count: unplaced.reduce((total, row) => total + row.complaints, 0) })}</p>}
    <details className="p-3 text-sm"><summary className="cursor-pointer text-muted">{t('csi.chartData')}</summary><table className="mt-2 w-full text-left"><thead><tr><th scope="col">{t('csi.region')}</th><th scope="col">{t('csi.complaints')}</th></tr></thead><tbody>{items.map(row => <tr key={row.region_code ?? 'unknown'}><td>{row.region_code ? names.get(row.region_code) ?? row.region_code : t('csi.unknown')}</td><td>{row.complaints}</td></tr>)}</tbody></table></details>
  </>
}
