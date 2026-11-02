import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { tEnum } from '@/shared/i18n'
import { formatExactRub } from '@/shared/lib/exactMoney'
import { fmtSimMoscow } from '@/shared/lib/format'
import { Empty, ErrorBox, Skeleton } from '@/shared/ui'
import { useOverview } from './api'

/** Explicit-run drilldown: legacy global dashboard/recompute hooks не монтируются. */
export function ScopedMetrics({ run }: { run: string }) {
  const { t, i18n } = useTranslation(), query = useOverview(run)
  const data = query.isError ? undefined : query.data
  const money = formatExactRub(data?.kpi.saved_rub_exact ?? null, i18n.language)
  const n = (value: number | null | undefined, suffix = '') => value == null ? '—' : new Intl.NumberFormat(i18n.language, { maximumFractionDigits: 1 }).format(value)+suffix
  return <div className="h-full min-w-0 space-y-4 overflow-auto p-4" data-scoped-metrics>
    <h1 className="text-2xl font-semibold">{t('overviewUi.scopedMetrics')}</h1>
    <p>{t('overviewUi.selectedRun', { run })}</p>
    <Link className="text-brand underline" to={`/overview?run_id=${encodeURIComponent(run)}`}>{t('overviewUi.title')}</Link>
    {query.isError ? <ErrorBox error={query.error} /> : query.isPending ? <Skeleton className="h-40" /> : data && <>
      {data.scope.current_missing && <Empty title={t('overviewUi.noCurrent')} />}
      <p className="text-sm text-muted">{fmtSimMoscow(data.as_of_sim)} · {t('overviewUi.kpiBasis')}</p>
      <dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{[
        ['signalsToday',n(data.kpi.signals_today)],['criticalToday',n(data.kpi.critical_today)],['autonomous',n(data.kpi.autonomous_share,'%')],['response',n(data.kpi.agent_response_p50_ms,' '+t('overviewUi.ms'))],['sla',n(data.kpi.sla_risk_incidents)],['saved',money.exact],
      ].map(([key,value]) => <div key={key} className="card p-4"><dt className="text-sm text-muted">{t('overviewUi.'+key)}</dt><dd className="num mt-2 break-words text-2xl">{value}</dd></div>)}</dl>
      <p className="text-sm text-muted">{t('overviewUi.savedHint')}</p>
      <p className="text-sm text-muted">{t('overviewUi.coverage', { signals: data.coverage.signals_today, criticality: data.coverage.criticality_known_today, runs: data.coverage.agent_runs, outcomes: data.coverage.outcome_known, latency: data.coverage.latency_known, economics: data.coverage.economics_known, incidents: data.coverage.incidents })}</p>
      <p className="text-sm text-muted">{t('overviewUi.slaCoverage', { known: data.coverage.sla_known, total: data.coverage.sla_open })}</p>
      <table className="w-full text-left"><caption className="py-3 text-left font-semibold">{t('overviewUi.pressure')}</caption><thead><tr><th>{t('common.status')}</th><th>{t('overviewUi.criticality')}</th><th>{t('overviewUi.incidents')}</th></tr></thead><tbody>{data.pressure.map(row => <tr key={row.status+row.criticality} className="border-t border-line"><td className="py-2">{tEnum('incident.status',row.status)}</td><td>{tEnum('incident.criticality',row.criticality)}</td><td className="num">{row.incidents}</td></tr>)}</tbody></table>
    </>}
  </div>
}
