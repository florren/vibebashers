import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { ROUTES } from '@/shared/routes'
import { projectionPoint, type ProjectedSignal } from './model'

export function SignalProjection({ rows, run }: { rows: ProjectedSignal[]; run: string | null }) {
  const { t } = useTranslation()
  const [focused, setFocused] = useState<number | null>(null)
  const known = rows.filter(row => row.negativity !== null && row.id !== undefined)
  return <div className="min-w-0">
    <svg viewBox="0 0 320 320" className="mx-auto block max-h-72 w-full max-w-80" role="group" aria-label={t('overviewUi.projection')}>
      {[42, 83, 125].map(radius => <circle key={radius} cx="160" cy="160" r={radius} fill="none" stroke="rgb(var(--line))" />)}
      <path d="M35 160H285M160 35V285" stroke="rgb(var(--line))" />
      <text x="164" y="155" fill="currentColor" fontSize="11">0</text><text x="282" y="153" fill="currentColor" fontSize="11" textAnchor="end">100</text>
      {known.map(row => { const point = projectionPoint(row.public_id ?? String(row.id), row.negativity!); const ref = row.public_id ?? String(row.id)
        return <Link key={row.id} to={`${ROUTES.traceObject('signal', ref)}?run_id=${encodeURIComponent(run ?? 'current')}`} aria-label={t('overviewUi.openSignal', { ref, negativity: row.negativity })} className="outline-none" onFocus={() => setFocused(row.id ?? null)} onBlur={() => setFocused(null)}>
          <title>{ref}: {row.negativity}</title><circle cx={point.x} cy={point.y} r="5" fill="rgb(var(--brand))" stroke={focused === row.id ? 'rgb(var(--focus-ring))' : 'rgb(var(--ink))'} strokeWidth={focused === row.id ? 3 : 1} />
        </Link> })}
    </svg>
    <p className="text-sm text-muted">{t('overviewUi.projectionHint')}</p><p className="text-xs text-muted">{t('overviewUi.projectionCoverage', { known: known.length, total: rows.length })}</p>
  </div>
}
