import { clsx } from 'clsx'
import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { useDashboard, useHitlQueue } from '@/shared/api/hooks'
import { fmtMs } from '@/shared/lib/format'

/** Верхняя полоса KPI: один запрос `/api/metrics/dashboard` (окно = текущий запуск, ТЗ 14.1) + размер очереди HITL. */
export function KpiStrip({ runId }: { runId: number | undefined }) {
  const { t } = useTranslation()
  const dash = useDashboard('run')
  const hitl = useHitlQueue({ run_id: runId })
  const d = dash.data
  const autonomy = d?.autonomous_share
  const critical = d?.critical_today ?? 0
  const slaRisk = (d?.sla_risk_count ?? 0) + (d?.sla_overdue_count ?? 0)
  const hitlN = hitl.data?.items?.length ?? 0

  return (
    <div className="grid grid-cols-4 gap-2 px-3 py-2 lg:grid-cols-8">
      <Kpi label={t('kpi.signals')} value={d?.signals_today ?? '—'} />
      <Kpi label={t('kpi.incidents')} value={d?.incidents_open ?? '—'} />
      <Kpi label={t('kpi.critical')} value={critical} tone={critical ? 'danger' : undefined} />
      <Kpi label={t('kpi.autonomy')} value={autonomy == null ? '—' : `${Math.round(autonomy)}%`} hint={t('kpi.hint.autonomy')} tone={autonomy != null && autonomy >= 70 ? 'ok' : undefined} />
      <Kpi label={t('kpi.hitl')} value={hitl.data ? hitlN : '—'} tone={hitlN > 0 ? 'warn' : undefined} />
      <Kpi label={t('kpi.slaRisk')} value={d ? slaRisk : '—'} hint={t('kpi.hint.slaRisk')} tone={(d?.sla_overdue_count ?? 0) > 0 ? 'danger' : slaRisk ? 'warn' : undefined} />
      <Kpi label={t('kpi.avgLatency')} value={fmtMs(d?.agent_latency_p50_ms ?? null)} hint={t('kpi.hint.latency')} />
      <Kpi label={t('kpi.tokens')} value={d ? new Intl.NumberFormat('ru-RU').format(d.tokens_total ?? 0) : '—'} />
    </div>
  )
}

function Kpi({ label, value, hint, tone }: { label: string; value: ReactNode; hint?: string; tone?: 'ok' | 'warn' | 'danger' }) {
  return (
    <div className="card px-3 py-2" title={hint}>
      <div className="truncate text-xs uppercase tracking-wide text-muted">{label}</div>
      <div
        className={clsx(
          'num mt-0.5 text-xl font-semibold leading-none',
          tone === 'danger' && 'text-danger',
          tone === 'warn' && 'text-warn',
          tone === 'ok' && 'text-ok',
        )}
      >
        {value}
      </div>
    </div>
  )
}
