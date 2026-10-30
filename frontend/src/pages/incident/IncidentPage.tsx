import { IncidentEconomics } from './IncidentEconomics'
import { JourneyLink } from '@/shared/components/JourneyLink'
import { IdLink } from '@/shared/components/IdLink'
import { ArrowLeft, Cpu } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useParams } from 'react-router-dom'
import type { Notification, Signal, StatusHistoryItem } from '@/shared/api/client'
import { listItems, useIncident, useIncidentComms, useIncidentHistory, useIncidentSignals, useRefName } from '@/shared/api/hooks'
import { tEnum } from '@/shared/i18n'
import { fmtSim, fmtDuration } from '@/shared/lib/format'
import { Badge, Empty, ErrorBox, KV, Section, Skeleton, SlaBar, Tabs } from '@/shared/ui'
import { criticalityTone, incidentStatusTone, severityTone } from '@/shared/ui/tones'
import { DecisionView } from '@/pages/workspace/SignalDrawer'
import { SignalRow } from '@/pages/workspace/SignalsFeed'
import { SignalDrawer } from '@/pages/workspace/SignalDrawer'
import { LogPanel } from '@/widgets/LogPanel'

type Tab = 'summary' | 'history' | 'signals' | 'comms' | 'economics'

/** Экран 2 «Карточка инцидента» (ТЗ 12.2) + LogPanel с шагами агента по прогону. */
export function IncidentPage() {
  const { t } = useTranslation()
  const { id: idStr } = useParams()
  const id = idStr ? Number(idStr) : null
  const q = useIncident(id)
  const team = useRefName('teams')
  const seg = useRefName('segments')
  const [tab, setTab] = useState<Tab>('summary')
  const [signalId, setSignalId] = useState<number | null>(null)
  const inc = q.data
  const runId = (inc as { agent_run_id?: number } | undefined)?.agent_run_id ?? null

  if (q.isPending)
    return (
      <div className="space-y-3 p-4">
        <Skeleton className="h-12" />
        <Skeleton className="h-48" />
      </div>
    )
  if (q.isError) return <ErrorBox error={q.error} />
  if (!inc) return <Empty title={t('incident.notFound')} />

  return (
    <div className="flex h-full">
      <div className="min-w-0 flex-1 overflow-y-auto">
        <div className="border-b border-line bg-surface px-4 py-3">
          <div className="mb-2 flex items-center gap-2">
            <Link to="/?tab=incidents" className="btn btn-ghost btn-sm">
              <ArrowLeft size={14} /> {t('common.back')}
            </Link>
            <IdLink kind="incident" value={inc.public_id} />
            <Link className="btn btn-sm" to={`/?tab=hitl&q=${encodeURIComponent(inc.public_id ?? '')}`}>{t('continuity.openHitl')}</Link>
            <JourneyLink reference={inc.public_id ?? `INC-${String(id).padStart(6, '0')}`} />
            <Badge tone={incidentStatusTone(inc.status)}>{tEnum('incident.status', inc.status)}</Badge>
            <Badge tone={criticalityTone(inc.criticality)}>
              P{inc.priority} · {tEnum('incident.criticality', inc.criticality)}
            </Badge>
            <Badge>{tEnum('incident.complexity', inc.complexity)}</Badge>
            {inc.routing_status && (
              <Badge tone={inc.routing_status === 'escalated' ? 'danger' : 'neutral'}>{tEnum('incident.routing', inc.routing_status)}</Badge>
            )}
            {(inc.flags ?? []).map((f) => (
              <Badge key={f} tone="warn">
                {tEnum('signal.flags', f)}
              </Badge>
            ))}
            <span className="mx-auto" />
            {runId && (
              <Link to={`/engine/${runId}`} className="btn btn-sm">
                <Cpu size={13} /> {t('incident.decisionChain')}
              </Link>
            )}
          </div>
          <h1 className="text-lg font-semibold leading-tight">{inc.title}</h1>
          <div className="mt-2 grid grid-cols-2 gap-x-6 gap-y-1 text-[13px] md:grid-cols-[1.6fr_1fr_1.5fr_1.2fr]">
            <KV
              k={t('incident.team')}
              v={
                <span>
                  {team(inc.team_code)}
                  {inc.co_team_codes?.length ? <span className="text-muted"> + {inc.co_team_codes.map(team).join(', ')}</span> : null}
                </span>
              }
            />
            <KV k={t('common.created')} v={<span className="num font-mono text-xs">{fmtSim(inc.created_sim, 'dd.MM HH:mm')}</span>} />
            <KV
              k={t('incident.slaDue')}
              v={
                <span className="num font-mono text-xs">
                  {fmtSim(inc.sla_due_sim, 'dd.MM HH:mm')} · {fmtDuration(inc.created_sim, inc.sla_due_sim)}
                </span>
              }
            />
            <div className="flex items-center gap-2 py-1">
              <span className="text-muted">{t('common.sla')}</span>
              <SlaBar pct={inc.sla_remaining_pct} breached={inc.sla_breached} className="flex-1" />
              <span className="num font-mono text-xs text-muted">
                {inc.sla_breached ? t('incident.slaBreached') : `${Math.round(inc.sla_remaining_pct ?? 0)}%`}
              </span>
            </div>
          </div>
        </div>

        <Tabs
          value={tab}
          onChange={setTab}
          items={[
            { id: 'summary', label: t('incident.summary') },
            { id: 'history', label: t('incident.history') },
            { id: 'signals', label: t('incident.signals') },
            { id: 'comms', label: t('incident.communications') },
            { id: 'economics', label: t('incident.economics') },
          ]}
        />

        <div className="space-y-3 p-4">
          {tab === 'summary' && (
            <>
              {inc.problem_summary && (
                <Section
                  title={t('incident.problem')}
                  right={<Badge tone={severityTone(inc.problem_summary.severity)}>{tEnum('incident.severity', inc.problem_summary.severity)}</Badge>}
                >
                  <div className="p-3 text-[13.5px] leading-relaxed">
                    {inc.problem_summary.problem}
                    <div className="mt-2 text-xs text-muted">
                      {t('incident.suggestedTeam')}: {team(inc.problem_summary.suggested_team)}
                    </div>
                  </div>
                </Section>
              )}
              <div className="grid gap-3 md:grid-cols-2">
                <Section title={t('incident.primaryClient')}>
                  <div className="px-3 py-1">
                    {inc.primary_client ? (
                      <>
                        <KV
                          k={inc.primary_client.display_name}
                          v={
                            <Badge tone={inc.primary_client.segment_code?.includes('vip') ? 'brand' : 'neutral'}>{seg(inc.primary_client.segment_code)}</Badge>
                          }
                        />
                        <KV k={inc.primary_client.city_name ?? '—'} v={<IdLink kind="client" value={inc.primary_client.public_id} />} />
                        <KV k="churn risk" v={<span className="num">{inc.primary_client.churn_risk ?? 0}</span>} />
                      </>
                    ) : (
                      <div className="py-1 text-sm text-muted">{t('signal.noClient')}</div>
                    )}
                    {(inc.mass_impact ?? 0) > 1 && <KV k={t('incident.massImpact')} v={<Badge tone="warn">{inc.mass_impact}</Badge>} />}
                  </div>
                </Section>
                <Section title={t('incident.fault')}>
                  <div className="px-3 py-1">
                    <KV
                      k="Продукт / система"
                      v={
                        <span className="font-mono text-xs">
                          {inc.product_code ?? '—'} · {inc.system_code ?? '—'}
                        </span>
                      }
                    />
                    {inc.fault ? (
                      <KV
                        k="fault"
                        v={
                          <span className="font-mono text-xs">
                            {String((inc.fault as Record<string, unknown>).error_code ?? (inc.fault as Record<string, unknown>).id ?? '')}
                          </span>
                        }
                      />
                    ) : (
                      <div className="py-1 text-sm text-muted">—</div>
                    )}
                    {inc.root_cause && <KV k={t('incident.rootCause')} v={inc.root_cause} />}
                    {inc.resolution_summary && <KV k={t('incident.resolution')} v={inc.resolution_summary} />}
                  </div>
                </Section>
              </div>
              {inc.decision && <DecisionView d={inc.decision} team={team} />}
              {!inc.decision && inc.agent_rationale_ru && (
                <Section title={t('signal.rationale')}>
                  <p className="p-3 text-[13px] leading-relaxed text-muted">{inc.agent_rationale_ru}</p>
                </Section>
              )}
            </>
          )}
          {tab === 'history' && <History id={id} />}
          {tab === 'signals' && <IncidentSignals id={id} onOpen={setSignalId} seg={seg} />}
          {tab === 'comms' && <Comms id={id} />}
          {tab === 'economics' && <IncidentEconomics id={id!} />}
        </div>
      </div>
      <aside className="hidden w-[380px] shrink-0 border-l border-line xl:block">
        <LogPanel runId={runId} />
      </aside>
      <SignalDrawer id={signalId} onClose={() => setSignalId(null)} />
    </div>
  )
}

function History({ id }: { id: number | null }) {
  const { t } = useTranslation()
  const q = useIncidentHistory(id)
  if (q.isPending) return <Skeleton className="h-32" />
  if (q.isError) return <ErrorBox error={q.error} />
  const rows = listItems<StatusHistoryItem>(q.data)
  if (!rows.length) return <Empty title={t('common.empty')} />
  return (
    <ol className="relative ml-2 border-l border-line">
      {rows.map((h, i) => (
        <li key={i} className="mb-3 ml-4">
          <span className="absolute -left-[5px] mt-1.5 h-2.5 w-2.5 rounded-full border-2 border-surface bg-brand" />
          <div className="flex items-center gap-2 text-[13px]">
            {h.from_status && (
              <>
                <Badge tone={incidentStatusTone(h.from_status)}>{tEnum('incident.status', h.from_status)}</Badge>
                <span className="text-faint">→</span>
              </>
            )}
            <Badge tone={incidentStatusTone(h.to_status)}>{tEnum('incident.status', h.to_status)}</Badge>
            <span className="text-xs text-muted">
              {h.actor_type}
              {h.actor_ref ? ` #${h.actor_ref}` : ''}
            </span>
            <span className="ml-auto num font-mono text-xs text-muted">{fmtSim(h.changed_sim, 'dd.MM HH:mm')}</span>
          </div>
          {h.reason && <div className="mt-0.5 text-xs text-muted">{h.reason}</div>}
        </li>
      ))}
    </ol>
  )
}

function IncidentSignals({ id, onOpen, seg }: { id: number | null; onOpen: (id: number) => void; seg: (c?: string | null) => string }) {
  const { t } = useTranslation()
  const q = useIncidentSignals(id)
  if (q.isPending) return <Skeleton className="h-32" />
  if (q.isError) return <ErrorBox error={q.error} />
  const signals = (q.data?.signals ?? q.data?.items ?? []) as Signal[]
  const logs = (q.data?.system_logs ?? []) as {
    id?: number
    level?: string
    system_code?: string
    error_code?: string | null
    component?: string
    message?: string
    logged_sim?: string
  }[]
  return (
    <div className="space-y-3">
      <Section title={t('tabs.signals')}>
        {signals.length ? (
          <ul className="divide-y divide-line">
            {signals.map((s) => (
              <SignalRow key={s.id} s={s} onOpen={onOpen} segName={seg} compact />
            ))}
          </ul>
        ) : (
          <Empty title={t('common.empty')} />
        )}
      </Section>
      <Section title="Системные логи">
        {logs.length ? (
          <ul className="divide-y divide-line font-mono text-xs">
            {logs.map((l) => (
              <li key={l.id} className="flex gap-2 px-3 py-1.5">
                <span className="num text-muted">{fmtSim(l.logged_sim, 'dd.MM HH:mm:ss')}</span>
                <Badge tone={l.level === 'ERROR' || l.level === 'error' ? 'danger' : l.level === 'WARN' || l.level === 'warning' ? 'warn' : 'neutral'}>
                  {l.level}
                </Badge>
                <span className="text-muted">
                  {l.system_code}
                  {l.component ? `/${l.component}` : ''}
                </span>
                {l.error_code && <span className="text-danger">{l.error_code}</span>}
                <span className="min-w-0 flex-1 truncate">{l.message}</span>
              </li>
            ))}
          </ul>
        ) : (
          <Empty title={t('common.empty')} />
        )}
      </Section>
    </div>
  )
}

function Comms({ id }: { id: number | null }) {
  const { t } = useTranslation()
  const q = useIncidentComms(id)
  if (q.isPending) return <Skeleton className="h-32" />
  if (q.isError) return <ErrorBox error={q.error} />
  const rows = listItems<Notification>((q.data as { notifications?: Notification[] })?.notifications ?? q.data)
  if (!rows.length) return <Empty title={t('common.empty')} />
  return (
    <ul className="space-y-2">
      {rows.map((n) => (
        <li key={n.id} className={`card max-w-2xl p-3 ${n.recipient_type === 'client' ? 'ml-0 border-l-4 border-brand' : 'ml-8'}`}>
          <div className="mb-1 flex items-center gap-2 text-xs text-muted">
            <Badge tone={n.recipient_type === 'client' ? 'brand' : 'neutral'}>
              {n.recipient_type === 'client' ? 'клиенту' : n.recipient_type === 'team' ? 'команде' : n.recipient_type}
            </Badge>
            <span>{tEnum('channel', n.channel_code)}</span>
            {n.template_code && <span className="font-mono">{n.template_code}</span>}
            <Badge tone={n.status === 'sent' || n.status === 'delivered' ? 'ok' : 'neutral'}>{n.status}</Badge>
            <span className="ml-auto num font-mono">{fmtSim(n.sent_sim, 'dd.MM HH:mm')}</span>
          </div>
          {n.subject && <div className="mb-0.5 text-[13px] font-medium">{n.subject}</div>}
          <div className="whitespace-pre-wrap text-[13px] leading-relaxed">{n.body}</div>
        </li>
      ))}
    </ul>
  )
}
