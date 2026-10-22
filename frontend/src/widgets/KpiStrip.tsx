import { clsx } from 'clsx'
import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { useAgentRuns, useHitlQueue, useIncidents, useSignals } from '@/shared/api/hooks'
import { fmtMs, fmtPct } from '@/shared/lib/format'
import { OPEN_STATUSES } from '@/shared/lib/statuses'

/**
 * Пока /api/metrics/dashboard не реализован (B14), KPI считаются на клиенте по спискам текущего прогона.
 * Используем limit=200 — для демо-объёмов достаточно; при появлении метрик заменить на один запрос.
 */
export function KpiStrip({ runId }: { runId: number | undefined }) {
  const { t } = useTranslation()
  const q = { run_id: runId, limit: 200 }
  const signals = useSignals(q)
  const incidents = useIncidents({ ...q, status: OPEN_STATUSES })
  const hitl = useHitlQueue({ run_id: runId })
  const runs = useAgentRuns(q)

  const sig = signals.data?.items ?? []
  const inc = incidents.data?.items ?? []
  const rs = runs.data?.items ?? []
  const finished = rs.filter((r) => r.outcome === 'completed' || r.outcome === 'awaiting_human')
  const autonomy = finished.length ? finished.filter((r) => !r.needed_human).length / finished.length : null
  const critical = inc.filter((i) => i.criticality === 'high').length
  const slaRisk = inc.filter((i) => i.sla_breached || (i.sla_remaining_pct ?? 100) < 25).length
  const avgLatency = rs.length ? rs.reduce((a, r) => a + (r.total_latency_ms ?? 0), 0) / rs.length : null
  const tokens = rs.reduce((a, r) => a + (r.total_tokens ?? 0), 0)

  return (
    <div className="grid grid-cols-4 gap-2 px-3 py-2 lg:grid-cols-8">
      <Kpi label={t('kpi.signals')} value={sig.length} />
      <Kpi label={t('kpi.incidents')} value={inc.length} />
      <Kpi label={t('kpi.critical')} value={critical} tone={critical ? 'danger' : undefined} />
      <Kpi label={t('kpi.autonomy')} value={fmtPct(autonomy)} hint={t('kpi.hint.autonomy')} tone={autonomy !== null && autonomy >= 0.7 ? 'ok' : undefined} />
      <Kpi label={t('kpi.hitl')} value={hitl.data?.items?.length ?? '—'} tone={(hitl.data?.items?.length ?? 0) > 0 ? 'warn' : undefined} />
      <Kpi label={t('kpi.slaRisk')} value={slaRisk} hint={t('kpi.hint.slaRisk')} tone={slaRisk ? 'danger' : undefined} />
      <Kpi label={t('kpi.avgLatency')} value={fmtMs(avgLatency === null ? null : Math.round(avgLatency))} />
      <Kpi label={t('kpi.tokens')} value={new Intl.NumberFormat('ru-RU').format(tokens)} />
    </div>
  )
}

function Kpi({ label, value, hint, tone }: { label: string; value: ReactNode; hint?: string; tone?: 'ok' | 'warn' | 'danger' }) {
  return (
    <div className="card px-3 py-2" title={hint}>
      <div className="truncate text-[11px] uppercase tracking-wide text-muted">{label}</div>
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
