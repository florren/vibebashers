import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { api, type Schemas } from '@/shared/api/client'
import { fmtSim } from '@/shared/lib/format'
import { formatMoney as fmtRub } from '@/pages/finance/money'
import { Empty, ErrorBox, Skeleton } from '@/shared/ui'
import { tEnum } from '@/shared/i18n'

export function IncidentEconomics({ id }: { id: number }) {
  const { t } = useTranslation()
  const query = useQuery({ queryKey: ['incident-economics', id], queryFn: () => api<Schemas['IncidentEconomics']>(`/api/incidents/${id}/economics`), refetchInterval: 5000 })
  if (query.isPending) return <Skeleton className="h-48" />
  if (query.isError) return <ErrorBox error={query.error} />
  const data = query.data
  if (!data) return <Empty title={t('common.empty')} />
  const rows = [
    ['affected', data.affected_count], ['rate', fmtRub(data.rate_rub)], ['premium', fmtRub(data.premium_addon_rub)],
    ['detractors', `${(data.detractor_share ?? 0) * 100}%`], ['noReturn', `${(data.no_return_share ?? 0) * 100}%`],
    ['retention', `${(data.retention_factor ?? 0) * 100}%`], ['potential', fmtRub(data.potential_loss_rub)],
    ['prevented', fmtRub(data.prevented_loss_rub)], ['realized', fmtRub(data.realized_loss_rub)],
    ['refund', fmtRub(data.refund_amount_rub)], ['net', fmtRub(data.net_effect_rub)],
  ] as const
  return <section className="card m-3 space-y-4 p-4">
    <Link className="text-info underline" to="/economics">{t('calculator.title')}</Link>
    <h2 className="text-lg font-semibold">{t('incident.economics')}</h2>
    <p className="rounded border border-line bg-raised p-3 font-mono text-sm">{data.formula_ru}</p>
    <dl className="grid grid-cols-2 gap-2 text-sm">{rows.map(([key, value]) => <div className="contents" key={key}><dt className="text-muted">{t(`incidentEconomics.${key}`)}</dt><dd className="num text-right">{value ?? '—'}</dd></div>)}</dl>
    <p className="text-xs text-muted">{data.rate_code} · {data.rate_reason}</p>
    <p className="text-xs">{t('incidentEconomics.outcome')}: {tEnum('outcome', data.outcome_class)} · {t(`incidentEconomics.source.${data.retention_source ?? 'manual'}`)}</p>
    {data.rate_code === 'misselling_case' && <p className="text-xs text-warn">{t('incidentEconomics.approval')}</p>}
    <p className="text-xs text-muted">{t('incidentEconomics.estimate')} · {fmtSim(data.computed_sim)}</p>
  </section>
}
