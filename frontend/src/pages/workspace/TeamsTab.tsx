import { useTranslation } from 'react-i18next'
import { clsx } from 'clsx'
import { useTeamsLoad } from '@/shared/api/hooks'
import { Empty, ErrorBox, SkeletonRows } from '@/shared/ui'

export function TeamsTab() {
  const { t } = useTranslation()
  const q = useTeamsLoad('current')
  const rows = q.data ?? []
  const max = Math.max(1, ...rows.map((r) => (r.open ?? 0) + (r.in_progress ?? 0)))
  return (
    <div className="p-3">
      <div className="mb-2 text-sm text-muted">{t('teams.subtitle')}</div>
      {q.error && <ErrorBox error={q.error} compact />}
      {q.isLoading && <SkeletonRows n={6} />}
      {!q.isLoading && rows.length === 0 && <Empty title={t('common.empty')} />}
      {rows.length > 0 && (
        <div className="overflow-x-auto"><table className="card w-full text-sm">
          <thead className="text-left text-[11px] uppercase tracking-wide text-muted">
            <tr className="border-b border-line">
              <th className="px-3 py-1.5 font-medium">{t('teams.col.team')}</th>
              <th className="w-1/4 px-3 py-1.5 font-medium">{t('teams.col.load')}</th>
              <th className="px-3 py-1.5 text-right font-medium">{t('teams.col.open')}</th>
              <th className="px-3 py-1.5 text-right font-medium">{t('teams.col.inProgress')}</th>
              <th className="px-3 py-1.5 text-right font-medium">{t('teams.col.slaWarning')}</th>
              <th className="px-3 py-1.5 text-right font-medium">{t('teams.col.slaBreached')}</th>
              <th className="px-3 py-1.5 text-right font-medium">{t('teams.col.reports')}</th>
              <th className="px-3 py-1.5 text-right font-medium">{t('teams.col.take')}</th>
              <th className="px-3 py-1.5 text-right font-medium">{t('teams.col.sla')}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {rows.map((r) => {
              const load = (r.open ?? 0) + (r.in_progress ?? 0)
              return (
                <tr key={r.team_code}>
                  <td className="px-3 py-1.5">
                    <div className="font-medium">{r.name_ru ?? r.team_code}</div>
                    <div className="text-[11px] text-muted">{r.lead_display_name}</div>
                  </td>
                  <td className="px-3 py-1.5">
                    <div className="flex h-2 w-full overflow-hidden rounded bg-raised">
                      <div className="h-2 bg-warn/80" style={{ width: `${(100 * (r.open ?? 0)) / max}%` }} />
                      <div className="h-2 bg-info/80" style={{ width: `${(100 * (r.in_progress ?? 0)) / max}%` }} />
                    </div>
                    <div className="mt-0.5 text-[11px] text-muted">{t('teams.loadOf', { n: load, total: r.total ?? 0 })}</div>
                  </td>
                  <td className="num px-3 py-1.5 text-right">{r.open}</td>
                  <td className="num px-3 py-1.5 text-right">{r.in_progress}</td>
                  <td className={clsx('num px-3 py-1.5 text-right', (r.sla_warning ?? 0) > 0 && 'text-warn')}>{r.sla_warning}</td>
                  <td className={clsx('num px-3 py-1.5 text-right', (r.sla_breached ?? 0) > 0 && 'text-danger')}>{r.sla_breached}</td>
                  <td className={clsx('num px-3 py-1.5 text-right', (r.reports_missing ?? 0) > 0 && 'text-danger')}>
                    {r.reports_due}
                    {(r.reports_missing ?? 0) > 0 && <span className="text-xs"> (−{r.reports_missing})</span>}
                  </td>
                  <td className="num px-3 py-1.5 text-right text-xs">{(r.avg_take_hours ?? 0) < 0.05 ? '—' : `${(r.avg_take_hours ?? 0).toFixed(1)} ч`}</td>
                  <td className={clsx('num px-3 py-1.5 text-right', (r.sla_compliance_pct ?? 100) < 80 ? 'text-danger' : (r.sla_compliance_pct ?? 100) < 95 ? 'text-warn' : 'text-ok')}>{r.sla_compliance_pct}%</td>
                </tr>
              )
            })}
          </tbody>
        </table></div>
      )}
      <p className="mt-2 text-xs text-muted">{t('teams.hint')}</p>
    </div>
  )
}
