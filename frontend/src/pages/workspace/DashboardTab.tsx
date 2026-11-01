import { Link } from 'react-router-dom'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { clsx } from 'clsx'
import { useCalibrate, useDashboard, useEconomics, useEconomicsFact, useRefName } from '@/shared/api/hooks'
import { fmtRub } from '@/shared/lib/format'
import { tEnum } from '@/shared/i18n'
import { Badge, ErrorBox, KV, Section, Skeleton } from '@/shared/ui'

type Win = 'run' | '24h' | '7d' | 'all'
const GROUPS = ['product', 'region', 'segment', 'team', 'type'] as const

export function DashboardTab() {
  const { t } = useTranslation()
  const [win, setWin] = useState<Win>('run')
  const [groupBy, setGroupBy] = useState<(typeof GROUPS)[number]>('product')
  const [showFact, setShowFact] = useState(false)
  const dash = useDashboard(win)
  const econ = useEconomics(groupBy, win === 'all' ? 'all' : 'current')
  const fact = useEconomicsFact(showFact)
  const calibrate = useCalibrate()
  const segName = useRefName('segments')
  const d = dash.data
  const e = econ.data

  return (
    <div className="flex flex-col gap-3 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-sm text-muted">{t('dash.subtitle')} · <Link className="text-info underline" to="/finance">{t('finance.title')}</Link></div>
        <div className="flex overflow-hidden rounded border border-line text-xs">
          {(['run', '24h', '7d', 'all'] as Win[]).map((w) => (
            <button key={w} type="button" className={clsx('px-2 py-0.5', win === w ? 'bg-brand-strong text-on-brand' : 'text-muted hover:text-ink')} onClick={() => setWin(w)}>
              {t(`dash.window.${w}`)}
            </button>
          ))}
        </div>
      </div>
      {dash.error && <ErrorBox error={dash.error} compact />}
      {!d && dash.isLoading && <Skeleton className="h-24" />}

      {d && (
        <>
          <div className="grid grid-cols-2 gap-2 md:grid-cols-4 xl:grid-cols-6">
            <Card label={t('dash.k.signals')} value={d.signals_total ?? d.signals_today ?? 0} sub={t('dash.k.criticalSub', { n: d.critical_total ?? d.critical_today ?? 0 })} />
            <Card label={t('dash.k.autonomy')} value={`${d.autonomous_share ?? 0}%`} sub={t('dash.k.hitlSub', { n: d.hitl_share ?? 0 })} tone={(d.autonomous_share ?? 0) >= 70 ? 'ok' : undefined} />
            <Card label={t('dash.k.humanChanged')} value={`${d.human_changed_share ?? 0}%`} sub={t('dash.k.humanChangedSub')} tone={(d.human_changed_share ?? 0) > 30 ? 'warn' : undefined} />
            <Card label={t('dash.k.incidentsOpen')} value={d.incidents_open ?? 0} sub={t('dash.k.incidentsSub', { n: d.incidents_total ?? 0, c: d.closed_loops ?? 0 })} />
            <Card label={t('dash.k.sla')} value={`${d.sla_compliance_pct ?? 0}%`} sub={t('dash.k.slaSub', { r: d.sla_risk_count ?? 0, o: d.sla_overdue_count ?? 0 })} tone={(d.sla_overdue_count ?? 0) > 0 ? 'danger' : (d.sla_risk_count ?? 0) > 0 ? 'warn' : 'ok'} />
            <Card label={t('dash.k.latency')} value={fmtMin(d.signal_to_incident_p50_min)} sub={t('dash.k.latencySub', { p95: fmtMin(d.signal_to_incident_p95_min), ms: d.agent_latency_p50_ms ?? 0 })} />
            <Card label={t('dash.k.repeat')} value={`${d.repeat_signals_share ?? 0}%`} sub={t('dash.k.repeatSub')} tone={(d.repeat_signals_share ?? 0) > 40 ? 'warn' : undefined} />
            <Card label={t('dash.k.churnRisk')} value={d.churn_risk_clients ?? 0} sub={t('dash.k.churnSub', { ch: d.churned_clients ?? 0, re: d.retained_clients ?? 0 })} tone={(d.churned_clients ?? 0) > 0 ? 'danger' : undefined} />
            <Card label={t('dash.k.closures')} value={d.account_closures ?? 0} sub={t('dash.k.regressionSub', { n: d.regression_share ?? 0 })} />
            <Card label={t('dash.k.twin')} value={d.twin_satisfaction_avg == null ? '—' : d.twin_satisfaction_avg} sub={t('dash.k.twinSub')} />
            <Card label={t('dash.k.tokens')} value={new Intl.NumberFormat('ru-RU').format(d.tokens_total ?? 0)} sub={t('dash.k.tokensSub', { n: d.agent_runs ?? 0 })} />
            <Card label={t('dash.k.reports')} value={`${d.reports_on_time_pct ?? 0}%`} sub={t('dash.k.reportsSub')} />
          </div>

          <div className="grid gap-3 lg:grid-cols-[1fr_360px]">
            <Section
              title={t('dash.econ.title')}
              right={
                <div className="flex items-center gap-2 text-xs">
                  <span className="text-muted">{t('dash.econ.groupBy')}</span>
                  <select className="input h-6 py-0 text-xs" value={groupBy} onChange={(ev) => setGroupBy(ev.target.value as (typeof GROUPS)[number])}>
                    {GROUPS.map((g) => (
                      <option key={g} value={g}>
                        {t(`dash.econ.group.${g}`)}
                      </option>
                    ))}
                  </select>
                </div>
              }
            >
              {e && (
                <>
                  <div className="grid grid-cols-2 gap-2 p-3 md:grid-cols-5">
                    <Money label={t('dash.econ.potential')} v={e.potential_loss_rub} hint={t('dash.econ.potentialHint')} />
                    <Money label={t('dash.econ.prevented')} v={e.prevented_loss_rub} tone="ok" hint={t('dash.econ.preventedHint')} />
                    <Money label={t('dash.econ.atRisk')} v={e.at_risk_open_rub} tone="warn" hint={t('dash.econ.atRiskHint')} />
                    <Money label={t('dash.econ.realized')} v={e.realized_loss_rub} tone={(e.realized_loss_rub ?? 0) > 0 ? 'danger' : undefined} hint={t('dash.econ.realizedHint')} />
                    <Money label={t('dash.econ.refunds')} v={e.refund_rub} hint={t('dash.econ.refundsHint')} />
                  </div>
                  <div className="overflow-x-auto"><table className="w-full text-sm">
                    <thead className="text-left text-[11px] uppercase tracking-wide text-muted">
                      <tr className="border-y border-line">
                        <th className="px-3 py-1.5 font-medium">{t(`dash.econ.group.${groupBy}`)}</th>
                        <th className="px-3 py-1.5 text-right font-medium">{t('dash.econ.incidents')}</th>
                        <th className="px-3 py-1.5 text-right font-medium">{t('dash.econ.potential')}</th>
                        <th className="px-3 py-1.5 text-right font-medium">{t('dash.econ.prevented')}</th>
                        <th className="px-3 py-1.5 text-right font-medium">{t('dash.econ.atRisk')}</th>
                        <th className="w-1/4 px-3 py-1.5" />
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-line">
                      {(e.groups ?? []).map((g) => {
                        const max = Math.max(1, ...(e.groups ?? []).map((x) => x.potential_loss_rub ?? 0))
                        const label = groupBy === 'type' ? tEnum('incidentType', g.key) : groupBy === 'segment' ? segName(g.key) : (g.label_ru ?? g.key)
                        return (
                          <tr key={g.key}>
                            <td className="px-3 py-1.5">{label === g.key && g.key === '—' ? t('dash.econ.noProduct') : label}</td>
                            <td className="num px-3 py-1.5 text-right">{g.incidents}</td>
                            <td className="num px-3 py-1.5 text-right">{fmtRub(g.potential_loss_rub)}</td>
                            <td className="num px-3 py-1.5 text-right text-ok">{fmtRub(g.prevented_loss_rub)}</td>
                            <td className="num px-3 py-1.5 text-right text-warn">{fmtRub(g.at_risk_open_rub)}</td>
                            <td className="px-3 py-1.5">
                              <div className="h-2 w-full rounded bg-raised">
                                <div className="h-2 rounded bg-danger/70" style={{ width: `${Math.max(2, (100 * (g.potential_loss_rub ?? 0)) / max)}%` }} />
                              </div>
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table></div>
                </>
              )}
            </Section>

            <div className="flex flex-col gap-3">
              <Section title={t('dash.segments.title')}>
                <div className="divide-y divide-line">
                  {Object.entries(d.first_response_by_segment ?? {}).map(([k, v]) => (
                    <KV key={k} k={segName(k)} v={fmtMin(v)} />
                  ))}
                  {Object.keys(d.first_response_by_segment ?? {}).length === 0 && <div className="px-3 py-2 text-xs text-muted">{t('common.empty')}</div>}
                </div>
              </Section>
              <Section
                title={t('dash.fact.title')}
                right={
                  <div className="flex items-center gap-1">
                    <Badge tone={e?.calibration_mode === 'simulated' ? 'info' : 'neutral'}>{t(`dash.fact.mode.${e?.calibration_mode ?? 'manual'}`)}</Badge>
                    <button className="btn btn-sm" onClick={() => setShowFact((v) => !v)}>
                      {showFact ? t('common.hide') : t('dash.fact.show')}
                    </button>
                  </div>
                }
              >
                <p className="px-3 py-2 text-xs leading-relaxed text-muted">{t('dash.fact.hint')}</p>
                {showFact && fact.data && (
                  <div className="divide-y divide-line border-t border-line">
                    {(['detractor_share', 'no_return_share'] as const).map((k) => {
                      const row = fact.data?.assumptions_vs_fact?.[k]
                      return <KV key={k} k={t(`dash.fact.${k}`)} v={`${pct(row?.assumed)} → ${row?.fact == null ? t('dash.fact.noData') : pct(row.fact)}`} />
                    })}
                    {Object.entries(fact.data.assumptions_vs_fact?.retention_factors ?? {}).map(([k, v]) => (
                      <KV key={k} k={tEnum('outcome', k)} v={`${pct(v.manual)} → ${v.simulated == null ? t('dash.fact.noData') : pct(v.simulated)} (n=${v.sample ?? 0})`} />
                    ))}
                    <div className="flex items-center justify-between gap-2 px-3 py-2">
                      <button className="btn btn-sm btn-primary" disabled={calibrate.isPending} onClick={() => calibrate.mutate(e?.calibration_mode === 'simulated' ? 'manual' : 'simulated')}>
                        {e?.calibration_mode === 'simulated' ? t('dash.fact.backToManual') : t('dash.fact.apply')}
                      </button>
                      <a className="btn btn-sm" href="/api/metrics/economics/fact/export?format=csv" target="_blank" rel="noreferrer">
                        CSV
                      </a>
                    </div>
                    {calibrate.error && <ErrorBox error={calibrate.error} compact />}
                  </div>
                )}
              </Section>
            </div>
          </div>
        </>
      )}
    </div>
  )
}

function fmtMin(v: number | null | undefined): string {
  if (v == null) return '—'
  if (v < 1) return '< 1 мин'
  return v < 60 ? `${Math.round(v)} мин` : `${(v / 60).toFixed(1)} ч`
}
function pct(v: number | null | undefined): string {
  return v == null ? '—' : `${Math.round(v * 100)}%`
}

function Card({ label, value, sub, tone }: { label: string; value: string | number; sub?: string; tone?: 'ok' | 'warn' | 'danger' }) {
  return (
    <div className="card px-3 py-2">
      <div className="truncate text-[11px] uppercase tracking-wide text-muted">{label}</div>
      <div className={clsx('num mt-0.5 text-xl font-semibold leading-none', tone === 'ok' && 'text-ok', tone === 'warn' && 'text-warn', tone === 'danger' && 'text-danger')}>{value}</div>
      {sub && <div className="mt-1 truncate text-[11px] text-muted" title={sub}>{sub}</div>}
    </div>
  )
}

function Money({ label, v, tone, hint }: { label: string; v: number | undefined; tone?: 'ok' | 'warn' | 'danger'; hint?: string }) {
  return (
    <div className="rounded-lg border border-line px-3 py-2" title={hint}>
      <div className="text-[11px] uppercase tracking-wide text-muted">{label}</div>
      <div className={clsx('num mt-0.5 text-lg font-semibold', tone === 'ok' && 'text-ok', tone === 'warn' && 'text-warn', tone === 'danger' && 'text-danger')}>{fmtRub(v)}</div>
    </div>
  )
}
