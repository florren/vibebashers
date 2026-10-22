import { clsx } from 'clsx'
import { FileText, RefreshCw } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQualityReport } from '@/shared/api/hooks'
import { tEnum } from '@/shared/i18n'
import { Badge, Empty, ErrorBox, SkeletonRows } from '@/shared/ui'

type Row = Record<string, unknown>

/** Вкладка «Качество» (T-222, docs/REPORTS.md): индекс здоровья, рекомендации, узлы агента, правки HITL, сценарии, HTTP. */
export function QualityTab() {
  const { t } = useTranslation()
  const [scope, setScope] = useState<'all' | 'current'>('all')
  const q = useQualityReport(scope)
  if (q.isPending) return <SkeletonRows />
  if (q.isError) return <ErrorBox error={q.error} />
  const rep = q.data
  const s = rep.summary as Row
  const health = Number(s.health ?? 0)
  const tone = health >= 80 ? 'ok' : health >= 50 ? 'warn' : 'danger'
  const nodes = ((rep.agent as Row | undefined)?.nodes ?? []) as Row[]
  const overrides = ((rep.hitl as Row | undefined)?.overrides ?? []) as Row[]
  const http = rep.http as Row | null | undefined
  const routes = ((http?.routes ?? []) as Row[]).filter((r) => Number(r.s5xx) || Number(r.s501) || Number(r.s4xx)).slice(0, 10)
  const kpis: [string, string | number][] = [
    [t('quality.k.runs'), `${s.agent_runs} · ${t('quality.k.failed')} ${s.agent_failed}`],
    [t('quality.k.fallback'), `${s.steps_fallback_pct} %`],
    [t('quality.k.hitl'), `${s.hitl_overridden} / ${s.hitl_decided} (${s.hitl_override_pct} %) · ${t('quality.k.pending')} ${s.hitl_pending}`],
    [t('quality.k.sla'), `${s.sla_breached} / ${s.incidents}`],
    [t('quality.k.scenarios'), `${(s.scenarios_failed as string[]).length} · ✓ ${s.scenarios_passed}`],
    [t('quality.k.alerts'), `${s.compliance_false_pct} % / ${s.compliance_alerts}`],
    [t('quality.k.http5'), s.http_5xx == null ? '—' : `${s.http_5xx} · 501: ${s.http_501}`],
  ]
  return (
    <div className="space-y-4 p-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className={clsx('flex h-14 w-14 items-center justify-center rounded-full border-4 text-lg font-bold', tone === 'ok' ? 'border-ok text-ok' : tone === 'warn' ? 'border-warn text-warn' : 'border-danger text-danger')}>{health}</div>
        <div>
          <div className="text-sm font-semibold">{t('quality.health')}</div>
          <div className="text-[11px] text-muted">
            {rep.version} · {String((s.generated_at as string) ?? '').slice(0, 16).replace('T', ' ')}
          </div>
        </div>
        <div className="ml-auto flex items-center gap-1 text-xs">
          <button className={clsx('btn btn-sm', scope === 'all' ? 'btn-primary' : 'btn-ghost')} onClick={() => setScope('all')}>
            {t('quality.allRuns')}
          </button>
          <button className={clsx('btn btn-sm', scope === 'current' ? 'btn-primary' : 'btn-ghost')} onClick={() => setScope('current')}>
            {t('quality.currentRun')}
          </button>
          <a className="btn btn-ghost btn-sm" href={`/api/reports/quality?run_id=${scope}&format=md`} target="_blank" rel="noreferrer">
            <FileText size={14} /> {t('quality.download')}
          </a>
          <button className="btn btn-ghost btn-sm" onClick={() => void q.refetch()} disabled={q.isFetching}>
            <RefreshCw size={14} className={q.isFetching ? 'animate-spin' : ''} /> {t('quality.refresh')}
          </button>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-2 md:grid-cols-4 xl:grid-cols-7">
        {kpis.map(([k, v]) => (
          <div key={k} className="card px-3 py-2">
            <div className="text-[11px] text-muted">{k}</div>
            <div className="num text-sm font-semibold">{v}</div>
          </div>
        ))}
      </div>
      <section className="card">
        <header className="flex h-9 items-center border-b border-line px-3 text-xs font-semibold uppercase tracking-wide text-muted">
          {t('quality.recommendations')} <span className="num ml-2">{rep.recommendations.length}</span>
        </header>
        <ul className="divide-y divide-line">
          {rep.recommendations.map((r, i) => (
            <li key={i} className="flex gap-3 p-3 text-sm">
              <Badge tone={r.severity === 'high' ? 'danger' : r.severity === 'medium' ? 'warn' : 'ok'}>{tEnum('quality.severity', r.severity)}</Badge>
              <div className="min-w-0 flex-1">
                <div>
                  <span className="mr-1 text-muted">[{tEnum('quality.area', r.area)}]</span>
                  {r.text}
                </div>
                <div className="mt-0.5 font-mono text-[11px] text-muted">
                  {t('quality.where')}: {r.where}
                </div>
              </div>
            </li>
          ))}
        </ul>
      </section>
      <section className="card">
        <header className="flex h-9 items-center border-b border-line px-3 text-xs font-semibold uppercase tracking-wide text-muted">{t('quality.nodes')}</header>
        {nodes.length === 0 ? (
          <div className="p-3 text-sm text-muted">{t('quality.empty')}</div>
        ) : (
          <table className="w-full text-xs">
            <thead className="text-left text-[11px] uppercase tracking-wide text-muted">
              <tr>
                <th className="px-3 py-1">{t('quality.col.node')}</th>
                <th className="num px-2 py-1 text-right">{t('quality.col.total')}</th>
                <th className="num px-2 py-1 text-right">{t('quality.col.ok')}</th>
                <th className="num px-2 py-1 text-right">{t('quality.col.fallback')}</th>
                <th className="num px-2 py-1 text-right">{t('quality.col.errors')}</th>
                <th className="num px-2 py-1 text-right">{t('quality.col.p50')}</th>
                <th className="num px-2 py-1 text-right">{t('quality.col.p95')}</th>
                <th className="num px-2 py-1 text-right">{t('quality.col.tokens')}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {nodes.map((n) => {
                const errs = Number(n.error) + Number(n.retry)
                return (
                  <tr key={String(n.node)} className={clsx(errs > 0 && 'bg-danger/5')}>
                    <td className="px-3 py-1 font-mono">{String(n.node)}</td>
                    <td className="num px-2 py-1 text-right">{String(n.total)}</td>
                    <td className="num px-2 py-1 text-right">{String(n.ok)}</td>
                    <td className={clsx('num px-2 py-1 text-right', Number(n.fallback) > 0 && 'text-warn')}>{String(n.fallback)}</td>
                    <td className={clsx('num px-2 py-1 text-right', errs > 0 && 'font-semibold text-danger')}>
                      {errs} ({String(n.error_rate)} %)
                    </td>
                    <td className="num px-2 py-1 text-right">{String(n.p50_ms)}</td>
                    <td className="num px-2 py-1 text-right">{String(n.p95_ms)}</td>
                    <td className="num px-2 py-1 text-right">{String(n.tokens)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </section>
      <section className="card">
        <header className="flex h-9 items-center border-b border-line px-3 text-xs font-semibold uppercase tracking-wide text-muted">
          {t('quality.hitl')} <span className="num ml-2">{overrides.length}</span>
        </header>
        {overrides.length === 0 ? (
          <div className="p-3 text-sm text-muted">{t('quality.noOverrides')}</div>
        ) : (
          <table className="w-full text-xs">
            <thead className="text-left text-[11px] uppercase tracking-wide text-muted">
              <tr>
                <th className="px-3 py-1">#</th>
                <th className="px-2 py-1">{t('quality.col.decision')}</th>
                <th className="px-2 py-1">{t('quality.col.reason')}</th>
                <th className="px-2 py-1">{t('quality.col.fields')}</th>
                <th className="px-2 py-1">{t('quality.col.comment')}</th>
                <th className="px-2 py-1">{t('quality.col.by')}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {overrides.map((o) => (
                <tr key={String(o.id)}>
                  <td className="num px-3 py-1">{String(o.id)}</td>
                  <td className="px-2 py-1">
                    <Badge tone={o.decision === 'reject' ? 'danger' : 'warn'}>{String(o.decision)}</Badge>
                  </td>
                  <td className="px-2 py-1">{String(o.reason ?? '—')}</td>
                  <td className="max-w-xs truncate px-2 py-1 font-mono text-[11px]" title={(o.changed_fields as string[]).join(', ')}>
                    {(o.changed_fields as string[]).join(', ') || '—'}
                  </td>
                  <td className="max-w-sm truncate px-2 py-1">{String(o.comment ?? '—')}</td>
                  <td className="px-2 py-1">{String(o.decided_by ?? '—')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
      <div className="grid gap-4 lg:grid-cols-2">
        <section className="card">
          <header className="flex h-9 items-center border-b border-line px-3 text-xs font-semibold uppercase tracking-wide text-muted">{t('quality.scenarios')}</header>
          <ul className="divide-y divide-line text-sm">
            {(rep.scenarios as Row[]).map((sc) => (
              <li key={String(sc.id)} className="flex items-start gap-2 px-3 py-1.5">
                <span className={clsx('mt-0.5 w-3 shrink-0 text-center', sc.passed === true ? 'text-ok' : sc.passed === false ? 'text-danger' : 'text-faint')}>
                  {sc.passed === true ? '✓' : sc.passed === false ? '✗' : '·'}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="mr-1 font-mono text-[11px] text-muted">{String(sc.id)}</span>
                  {String(sc.title_ru)}
                  {(sc.failed_checks as Row[]).length > 0 && <span className="text-danger"> — {(sc.failed_checks as Row[]).map((c) => String(c.code)).join(', ')}</span>}
                </span>
              </li>
            ))}
          </ul>
        </section>
        <section className="card">
          <header className="flex h-9 items-center border-b border-line px-3 text-xs font-semibold uppercase tracking-wide text-muted">
            {t('quality.http')}
            {http && (
              <span className="num ml-2 normal-case">
                {String(http.requests)} · 5xx {String(http.s5xx)} · 501 {String(http.s501)} · 4xx {String(http.s4xx)}
              </span>
            )}
          </header>
          {!http || routes.length === 0 ? (
            <Empty title={t('quality.empty')} />
          ) : (
            <table className="w-full text-xs">
              <thead className="text-left text-[11px] uppercase tracking-wide text-muted">
                <tr>
                  <th className="px-3 py-1">{t('quality.col.route')}</th>
                  <th className="num px-2 py-1 text-right">{t('quality.col.total')}</th>
                  <th className="num px-2 py-1 text-right">{t('quality.col.s5xx')}</th>
                  <th className="num px-2 py-1 text-right">{t('quality.col.s501')}</th>
                  <th className="num px-2 py-1 text-right">{t('quality.col.s4xx')}</th>
                  <th className="num px-2 py-1 text-right">{t('quality.col.avg')}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {routes.map((r) => (
                  <tr key={`${r.method} ${r.route}`}>
                    <td className="px-3 py-1 font-mono">
                      {String(r.method)} {String(r.route)}
                    </td>
                    <td className="num px-2 py-1 text-right">{String(r.total)}</td>
                    <td className={clsx('num px-2 py-1 text-right', Number(r.s5xx) > 0 && 'font-semibold text-danger')}>{String(r.s5xx)}</td>
                    <td className="num px-2 py-1 text-right">{String(r.s501)}</td>
                    <td className="num px-2 py-1 text-right">{String(r.s4xx)}</td>
                    <td className="num px-2 py-1 text-right">{String(r.avg_ms)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      </div>
    </div>
  )
}
