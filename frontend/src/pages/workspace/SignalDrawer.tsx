import { IdLink } from '@/shared/components/IdLink'
import { ExternalLink } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import type { Decision } from '@/shared/api/client'
import { useRefName, useSignal } from '@/shared/api/hooks'
import { tEnum } from '@/shared/i18n'
import { fmtSim, shortId } from '@/shared/lib/format'
import { Badge, Drawer, ErrorBox, KV, Section, Skeleton } from '@/shared/ui'
import { criticalityTone, incidentStatusTone, sentimentTone, severityTone, signalStatusTone } from '@/shared/ui/tones'

export function SignalDrawer({ id, onClose }: { id: number | null; onClose: () => void }) {
  const { t } = useTranslation()
  const q = useSignal(id)
  const s = q.data
  const team = useRefName('teams')
  const seg = useRefName('segments')
  const c = s?.classification
  const d = s?.decision ?? null

  return (
    <Drawer open={id !== null} onClose={onClose} title={<IdLink kind="signal" value={shortId(id ?? undefined, 'SIG')} />}>
      {q.isPending && (
        <div className="space-y-3 p-4">
          <Skeleton className="h-16" />
          <Skeleton className="h-32" />
          <Skeleton className="h-24" />
        </div>
      )}
      {q.isError && <ErrorBox error={q.error} />}
      {s && (
        <div className="space-y-3 p-4">
          <Link className="btn btn-sm" to={`/?tab=hitl&q=${encodeURIComponent(s.public_id ?? '')}`} onClick={onClose}>{t('continuity.openHitl')}</Link>
          <div className="flex flex-wrap items-center gap-1.5">
            <Badge tone={signalStatusTone(s.status)}>{tEnum('signal.status', s.status)}</Badge>
            <Badge>{tEnum('channel', s.channel_code)}</Badge>
            {s.origin && <Badge>{tEnum('signal.origin', s.origin)}</Badge>}
            <span className="ml-auto num font-mono text-xs text-muted">{fmtSim(s.received_sim, 'dd.MM.yyyy HH:mm')}</span>
          </div>
          <blockquote className="rounded-xl border-l-4 border-brand bg-raised p-3 text-[13.5px] leading-relaxed">{s.text}</blockquote>

          <Section title={t('common.client')}>
            <div className="px-3 py-1">
              {s.client ? (
                <>
                  <KV
                    k={s.client.display_name}
                    v={
                      <Badge tone={s.client.segment_code === 'ultra_vip' || s.client.segment_code === 'vip' ? 'brand' : 'neutral'}>
                        {seg(s.client.segment_code)}
                      </Badge>
                    }
                  />
                  <KV k={s.client.city_name ?? '—'} v={<IdLink kind="client" value={s.client.public_id} />} />
                  {s.client.churn_risk !== undefined && <KV k="churn risk" v={<span className="num">{s.client.churn_risk ?? 0}</span>} />}
                </>
              ) : (
                <div className="py-1 text-sm text-muted">{s.external_contact?.nick ? `@${s.external_contact.nick}` : t('signal.noClient')}</div>
              )}
            </div>
          </Section>

          {c && (
            <Section
              title={t('signal.classification')}
              right={
                c.confidence !== undefined ? (
                  <span className="num text-xs text-muted">
                    {t('common.confidence')} {Math.round(c.confidence * 100)}%
                  </span>
                ) : null
              }
            >
              <div className="px-3 py-1">
                <KV k={t('common.type')} v={<Badge tone="info">{tEnum('signal.type', c.signal_type)}</Badge>} />
                <KV k="Критичность" v={<Badge tone={criticalityTone(c.criticality)}>{tEnum('incident.criticality', c.criticality)}</Badge>} />
                {c.sentiment && (
                  <KV
                    k="Тональность"
                    v={
                      <Badge tone={sentimentTone(c.sentiment)}>
                        {tEnum('signal.sentiment', c.sentiment)}
                        {c.negativity !== undefined ? ` · ${c.negativity}` : ''}
                      </Badge>
                    }
                  />
                )}
                {c.product && <KV k="Продукт" v={c.product} mono />}
                {c.system && <KV k="Система" v={`${c.system}${c.error_code ? ` · ${c.error_code}` : ''}`} mono />}
                {(c.flags?.length ?? 0) > 0 && (
                  <KV
                    k="Флаги"
                    v={
                      <span className="flex flex-wrap justify-end gap-1">
                        {(c.flags as string[]).map((f) => (
                          <Badge key={f} tone="warn">
                            {tEnum('signal.flags', f)}
                          </Badge>
                        ))}
                      </span>
                    }
                  />
                )}
                {c.problem_summary && (
                  <div className="mt-1 rounded-lg bg-raised p-2 text-[13px]">
                    <div className="mb-1 flex items-center gap-2 text-xs text-muted">
                      {t('incident.problem')}{' '}
                      <Badge tone={severityTone(c.problem_summary.severity)}>{tEnum('incident.severity', c.problem_summary.severity)}</Badge>
                      <span className="ml-auto">{team(c.problem_summary.suggested_team)}</span>
                    </div>
                    {c.problem_summary.problem}
                  </div>
                )}
                {c.rationale_ru && <p className="mt-2 text-xs leading-relaxed text-muted">{c.rationale_ru}</p>}
              </div>
            </Section>
          )}

          {d && <DecisionView d={d} team={team} />}

          {(s.incidents?.length ?? 0) > 0 && (
            <Section title={t('signal.incidents')}>
              <ul className="divide-y divide-line">
                {s.incidents!.map((i) => (
                  <li key={i.id} className="flex items-center gap-2 px-3 py-2 text-[13px]">
                    <Badge tone={incidentStatusTone(i.status)}>{tEnum('incident.status', i.status)}</Badge>
                    <span className="min-w-0 flex-1 truncate">{i.title}</span>
                    <span className="text-xs text-muted">{team(i.team_code)}</span>
                    <Link className="btn btn-ghost btn-sm" to={`/incidents/${i.id}`} onClick={onClose}>
                      <ExternalLink size={12} />
                    </Link>
                  </li>
                ))}
              </ul>
            </Section>
          )}

          {(s.notifications?.length ?? 0) > 0 && (
            <Section title={t('signal.notifications')}>
              <ul className="divide-y divide-line">
                {s.notifications!.map((n) => (
                  <li key={n.id} className="px-3 py-2 text-[13px]">
                    <div className="mb-0.5 flex items-center gap-2 text-xs text-muted">
                      <Badge tone={n.recipient_type === 'client' ? 'brand' : 'neutral'}>
                        {n.recipient_type === 'client' ? 'клиенту' : n.recipient_type === 'team' ? 'команде' : n.recipient_type}
                      </Badge>
                      <span>{tEnum('channel', n.channel_code)}</span>
                      {n.template_code && <span className="font-mono">{n.template_code}</span>}
                      <span className="ml-auto num font-mono">{fmtSim(n.sent_sim)}</span>
                    </div>
                    <div className="whitespace-pre-wrap leading-relaxed">{n.body}</div>
                  </li>
                ))}
              </ul>
            </Section>
          )}

          {(s.agent_runs?.length ?? 0) > 0 && (
            <Section title={t('signal.runs')}>
              <ul className="divide-y divide-line">
                {s.agent_runs!.map((r) => (
                  <li key={r.id} className="flex items-center gap-2 px-3 py-2 text-[13px]">
                    <span className="font-mono text-xs">#{r.id}</span>
                    <Badge tone={r.outcome === 'completed' ? 'ok' : r.outcome === 'awaiting_human' ? 'warn' : r.outcome === 'failed' ? 'danger' : 'neutral'}>
                      {tEnum('engine.outcome', r.outcome ?? 'running')}
                    </Badge>
                    <span className="text-xs text-muted">
                      {r.llm_profile_code} · {r.prompt_version} · {r.total_tokens} ток.
                    </span>
                    <Link className="btn btn-ghost btn-sm ml-auto" to={`/engine/${r.id}`} onClick={onClose}>
                      {t('nav.engine')} <ExternalLink size={12} />
                    </Link>
                  </li>
                ))}
              </ul>
            </Section>
          )}
        </div>
      )}
    </Drawer>
  )
}

export function DecisionView({ d, team }: { d: Decision; team: (c: string | null | undefined) => string }) {
  const { t } = useTranslation()
  return (
    <Section title={t('signal.decision')} right={d.fast_path ? <Badge tone="brand">fast path</Badge> : null}>
      <div className="px-3 py-1">
        <KV
          k="Действие"
          v={
            <span className="font-mono text-xs">
              {d.router_action} · {d.incident_action}
            </span>
          }
        />
        {d.route?.team && (
          <KV k={t('common.team')} v={`${team(d.route.team)}${d.route.co_teams?.length ? ` + ${d.route.co_teams.map(team).join(', ')}` : ''}`} />
        )}
        {d.priority !== undefined && (
          <KV
            k={t('common.priority')}
            v={
              <span className="num">
                P{d.priority} · {tEnum('incident.complexity', d.complexity)} · {tEnum('incident.criticality', d.criticality)}
              </span>
            }
          />
        )}
        {d.sla && (
          <KV
            k={t('common.sla')}
            v={
              <span className="num">
                {d.sla.fix_days} д · взять за {d.sla.take_hours} ч · до {fmtSim(d.sla.due_sim)}
              </span>
            }
          />
        )}
        {d.needs_human && <KV k={t('engine.needHuman')} v={<Badge tone="warn">{tEnum('hitl.reason', d.human_reason)}</Badge>} />}
        {(d.rule_codes?.length ?? 0) > 0 && <KV k={t('incident.ruleCodes')} v={<span className="font-mono text-xs">{d.rule_codes!.join(', ')}</span>} />}
        {d.client_action?.text_ru && (
          <div className="mt-1 rounded-lg bg-brand-soft/60 p-2 text-[13px] leading-relaxed">
            <div className="mb-0.5 text-xs text-muted">
              {t('incident.clientReply')} · {d.client_action.kind}
              {d.client_action.channel ? ` · ${tEnum('channel', d.client_action.channel)}` : ''}
            </div>
            {d.client_action.text_ru}
          </div>
        )}
        {d.clarification_question_ru && <div className="mt-1 rounded-lg bg-warn/10 p-2 text-[13px]">{d.clarification_question_ru}</div>}
        {d.team_notice_ru && (
          <div className="mt-1 rounded-lg bg-raised p-2 text-[13px] leading-relaxed">
            <div className="mb-0.5 text-xs text-muted">{t('incident.teamNotice')}</div>
            {d.team_notice_ru}
          </div>
        )}
        {d.gift && (
          <KV
            k={t('incident.gift')}
            v={
              <span>
                {d.gift.gift_code}
                {d.gift.points ? ` · ${d.gift.points} б.` : ''}
                {d.gift.requires_hitl ? ' · HITL' : ''}
              </span>
            }
          />
        )}
        {d.followup && <KV k={t('incident.followup')} v={`через ${d.followup.wake_in_sim_hours} ч · ${d.followup.reason}`} />}
        {d.escalation && (
          <KV
            k="Эскалация"
            v={
              <Badge tone="danger">
                {d.escalation.to_role} · {d.escalation.reason}
              </Badge>
            }
          />
        )}
        {d.rationale_ru && <p className="mt-2 text-xs leading-relaxed text-muted">{d.rationale_ru}</p>}
        {(d.policy_checks?.length ?? 0) > 0 && (
          <details className="mt-2">
            <summary className="cursor-pointer text-xs text-muted">
              {t('signal.policies')} ({d.policy_checks!.filter((p) => p.passed).length}/{d.policy_checks!.length})
            </summary>
            <ul className="mt-1 space-y-0.5">
              {d.policy_checks!.map((p, i) => (
                <li key={i} className="flex items-center gap-2 text-xs">
                  <span className={p.passed ? 'text-ok' : 'text-danger'}>{p.passed ? '✓' : '✗'}</span>
                  <span className="font-mono">{p.rule}</span>
                  {p.note && <span className="text-muted">— {p.note}</span>}
                </li>
              ))}
            </ul>
          </details>
        )}
      </div>
    </Section>
  )
}
