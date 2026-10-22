import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { clsx } from 'clsx'
import { useAckEscalation, useCreateEscalation, useEscalation, useEscalations, useIncidentAction, useRefName, useRefs, useTicket, useTickets } from '@/shared/api/hooks'
import type { Escalation, Ticket } from '@/shared/api/client'
import { fmtSim } from '@/shared/lib/format'
import { tEnum } from '@/shared/i18n'
import { Badge, Drawer, Empty, ErrorBox, KV, Section, SkeletonRows } from '@/shared/ui'
import { criticalityTone, incidentStatusTone, severityTone } from '@/shared/ui/tones'

type View = 'tickets' | 'escalations'
const T_STATUSES = ['open', 'in_progress', 'resolved', 'closed', 'rejected'] as const
const E_STATUSES = ['open', 'acknowledged', 'resolved', 'dismissed'] as const

export function TicketsTab({ runId }: { runId: number | undefined }) {
  const { t } = useTranslation()
  const [view, setView] = useState<View>('tickets')
  const [tStatus, setTStatus] = useState<string[]>(['open', 'in_progress'])
  const [eStatus, setEStatus] = useState<string[]>(['open', 'acknowledged'])
  const [dept, setDept] = useState<string>('')
  const [onlyEsc, setOnlyEsc] = useState(false)
  const [q, setQ] = useState('')
  const [ticketId, setTicketId] = useState<number | null>(null)
  const [escId, setEscId] = useState<number | null>(null)
  const teams = useRefs('teams')
  const teamName = useRefName('teams')
  const tickets = useTickets({ run_id: runId, status: tStatus, department: dept || undefined, escalated: onlyEsc ? true : undefined, q: q || undefined, limit: 200 })
  const escs = useEscalations({ run_id: runId, status: eStatus, limit: 200 })

  const toggle = (arr: string[], v: string, set: (a: string[]) => void) => set(arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v])

  return (
    <div className="p-3">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <div className="flex overflow-hidden rounded border border-line text-xs">
          {(['tickets', 'escalations'] as View[]).map((v) => (
            <button key={v} type="button" className={clsx('px-2 py-0.5', view === v ? 'bg-brand text-white' : 'text-muted hover:text-ink')} onClick={() => setView(v)}>
              {t(`tickets.view.${v}`)}
              {v === 'escalations' && (escs.data?.counts?.open ?? 0) > 0 && <span className="ml-1 rounded-full bg-danger px-1.5 text-[10px] text-white">{escs.data?.counts?.open}</span>}
            </button>
          ))}
        </div>
        {view === 'tickets' ? (
          <>
            {T_STATUSES.map((s) => (
              <button key={s} className={clsx('chip', tStatus.includes(s) && 'chip-on')} onClick={() => toggle(tStatus, s, setTStatus)}>
                {t(`tickets.status.${s}`)}
              </button>
            ))}
            <select className="input h-6 py-0 text-xs" value={dept} onChange={(e) => setDept(e.target.value)}>
              <option value="">{t('tickets.allDepartments')}</option>
              {(teams.data ?? []).map((tm) => (
                <option key={tm.code} value={tm.code}>
                  {tm.name_ru}
                </option>
              ))}
            </select>
            <button className={clsx('chip', onlyEsc && 'chip-on')} onClick={() => setOnlyEsc((v) => !v)}>
              {t('tickets.onlyEscalated')}
            </button>
            <input className="input h-6 w-44 text-xs" placeholder={t('tickets.search')} value={q} onChange={(e) => setQ(e.target.value)} />
            <span className="ml-auto text-xs text-muted">{t('common.items', { n: tickets.data?.total ?? 0 })}</span>
          </>
        ) : (
          <>
            {E_STATUSES.map((s) => (
              <button key={s} className={clsx('chip', eStatus.includes(s) && 'chip-on')} onClick={() => toggle(eStatus, s, setEStatus)}>
                {t(`tickets.escStatus.${s}`)}
              </button>
            ))}
            <span className="ml-auto text-xs text-muted">{t('tickets.escHint')}</span>
          </>
        )}
      </div>

      {view === 'tickets' && (
        <>
          {tickets.error && <ErrorBox error={tickets.error} compact />}
          {tickets.isLoading && <SkeletonRows n={8} />}
          {!tickets.isLoading && (tickets.data?.items ?? []).length === 0 && <Empty title={t('tickets.empty')} hint={t('tickets.emptyHint')} />}
          {(tickets.data?.items ?? []).length > 0 && (
            <table className="card w-full text-sm">
              <thead className="text-left text-[11px] uppercase tracking-wide text-muted">
                <tr className="border-b border-line">
                  <th className="px-3 py-1.5 font-medium">{t('tickets.col.ticket')}</th>
                  <th className="px-3 py-1.5 font-medium">{t('tickets.col.summary')}</th>
                  <th className="px-3 py-1.5 font-medium">{t('tickets.col.department')}</th>
                  <th className="px-3 py-1.5 font-medium">{t('tickets.col.priority')}</th>
                  <th className="px-3 py-1.5 font-medium">{t('tickets.col.status')}</th>
                  <th className="px-3 py-1.5 font-medium">{t('tickets.col.channel')}</th>
                  <th className="px-3 py-1.5 font-medium">{t('tickets.col.created')}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {(tickets.data?.items ?? []).map((tk) => (
                  <TicketRow key={tk.incident_id} tk={tk} teamName={teamName} onOpen={() => setTicketId(tk.incident_id ?? null)} />
                ))}
              </tbody>
            </table>
          )}
        </>
      )}

      {view === 'escalations' && (
        <>
          {escs.error && <ErrorBox error={escs.error} compact />}
          {escs.isLoading && <SkeletonRows n={6} />}
          {!escs.isLoading && (escs.data?.items ?? []).length === 0 && <Empty title={t('tickets.escEmpty')} hint={t('tickets.escEmptyHint')} />}
          <ul className="grid gap-2 lg:grid-cols-2">
            {(escs.data?.items ?? []).map((e) => (
              <EscCard key={e.id} e={e} onOpen={() => setEscId(e.id ?? null)} />
            ))}
          </ul>
        </>
      )}

      <TicketDrawer id={ticketId} onClose={() => setTicketId(null)} onOpenEsc={(id) => setEscId(id)} />
      <EscDrawer id={escId} onClose={() => setEscId(null)} />
    </div>
  )
}

function TicketRow({ tk, teamName, onOpen }: { tk: Ticket; teamName: (c: string | null | undefined) => string; onOpen: () => void }) {
  const { t } = useTranslation()
  return (
    <tr className="cursor-pointer hover:bg-raised" onClick={onOpen}>
      <td className="num whitespace-nowrap px-3 py-1.5 font-mono text-xs">
        {tk.ticket_id}
        {tk.escalated && <Badge tone="danger" className="ml-1">{t('tickets.escalatedBadge')}</Badge>}
      </td>
      <td className="max-w-[420px] truncate px-3 py-1.5" title={tk.summary}>
        {tk.summary}
        {tk.client_name && <span className="ml-1 text-xs text-muted">· {tk.client_name}</span>}
      </td>
      <td className="px-3 py-1.5 text-xs">{teamName(tk.department)}</td>
      <td className="num px-3 py-1.5 text-xs">
        P{tk.priority} <Badge tone={criticalityTone(tk.criticality)}>{tEnum('incident.criticality', tk.criticality)}</Badge>
      </td>
      <td className="px-3 py-1.5">
        <Badge tone={incidentStatusTone(tk.incident_status)}>{tEnum('incident.status', tk.incident_status)}</Badge>
      </td>
      <td className="px-3 py-1.5 text-xs text-muted">{tEnum('channel', tk.channel)}</td>
      <td className="num whitespace-nowrap px-3 py-1.5 text-xs text-muted">{fmtSim(tk.created_at)}</td>
    </tr>
  )
}

function EscCard({ e, onOpen }: { e: Escalation; onOpen: () => void }) {
  const { t } = useTranslation()
  const ack = useAckEscalation()
  const [res, setRes] = useState('')
  const open = e.status === 'open' || e.status === 'acknowledged'
  return (
    <li className={clsx('card p-3', e.severity === 'critical' && open && 'ring-1 ring-danger/50')}>
      <div className="flex items-center gap-2">
        <button className="num font-mono text-xs text-muted hover:text-brand" onClick={onOpen}>
          {e.public_id}
        </button>
        <Badge tone={severityTone(e.severity)}>{tEnum('incident.severity', e.severity)}</Badge>
        <Badge tone={e.status === 'open' ? 'danger' : e.status === 'acknowledged' ? 'warn' : 'neutral'}>{t(`tickets.escStatus.${e.status ?? 'open'}`)}</Badge>
        <span className="text-xs text-muted">→ {t(`tickets.role.${e.to_role ?? 'cx_lead'}`)}</span>
        <span className="ml-auto text-xs text-muted">{fmtSim(e.created_sim)}</span>
      </div>
      <div className="mt-1.5 text-sm">
        <span className="font-medium">{tEnum('tickets.escReason', e.reason)}</span>
        {e.incident_title && <span className="text-muted"> · {e.incident_title}</span>}
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted">
        {e.ticket_id && (
          <Link to={`/incidents/${e.incident_id}`} className="font-mono hover:text-brand">
            {e.ticket_id}
          </Link>
        )}
        {e.client_name && <span>{e.client_name}</span>}
        {e.channel && <span>{tEnum('channel', e.channel)}</span>}
        <span>{t(`tickets.by.${e.created_by ?? 'agent'}`)}</span>
        {e.acknowledged_by && <span>· {t('tickets.ackBy', { who: e.acknowledged_by })}</span>}
      </div>
      {e.resolution_ru && <div className="mt-1.5 rounded bg-raised px-2 py-1 text-xs">{e.resolution_ru}</div>}
      {open && (
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          {e.status === 'open' && (
            <button className="btn btn-sm" disabled={ack.isPending} onClick={() => ack.mutate({ id: e.id ?? 0, status: 'acknowledged', actor: 'cx_lead' })}>
              {t('tickets.act.ack')}
            </button>
          )}
          <input className="input h-7 min-w-0 flex-1 text-xs" placeholder={t('tickets.resolutionPh')} value={res} onChange={(ev) => setRes(ev.target.value)} />
          <button className="btn btn-sm btn-primary" disabled={ack.isPending || res.trim().length < 3} onClick={() => ack.mutate({ id: e.id ?? 0, status: 'resolved', resolution_ru: res, actor: 'cx_lead' })}>
            {t('tickets.act.resolve')}
          </button>
          <button className="btn btn-sm" disabled={ack.isPending || res.trim().length < 3} onClick={() => ack.mutate({ id: e.id ?? 0, status: 'dismissed', resolution_ru: res, actor: 'cx_lead' })}>
            {t('tickets.act.dismiss')}
          </button>
        </div>
      )}
      {ack.error && <ErrorBox error={ack.error} compact />}
    </li>
  )
}

function TicketDrawer({ id, onClose, onOpenEsc }: { id: number | null; onClose: () => void; onOpenEsc: (id: number) => void }) {
  const { t } = useTranslation()
  const q = useTicket(id)
  const act = useIncidentAction(id)
  const esc = useCreateEscalation()
  const teams = useRefs('teams')
  const teamName = useRefName('teams')
  const [text, setText] = useState('')
  const [team, setTeam] = useState('')
  const d = q.data
  const closed = d?.incident_status === 'closed' || d?.incident_status === 'rejected' || d?.incident_status === 'duplicate'
  return (
    <Drawer open={id !== null} onClose={onClose} title={d ? `${d.ticket_id} · ${d.summary}` : '…'} width="w-[680px]">
      {q.error && <ErrorBox error={q.error} />}
      {d && (
        <div className="flex flex-col gap-3 p-3">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={incidentStatusTone(d.incident_status)}>{tEnum('incident.status', d.incident_status)}</Badge>
            <Badge tone={criticalityTone(d.criticality)}>P{d.priority} · {tEnum('incident.criticality', d.criticality)}</Badge>
            <span className="text-xs text-muted">{teamName(d.department)}</span>
            {d.escalated && <Badge tone="danger">{t('tickets.escalatedBadge')}</Badge>}
            <Link to={`/incidents/${d.incident_id}`} className="btn btn-sm ml-auto">
              {t('tickets.openIncident')}
            </Link>
          </div>

          <Section title={t('tickets.actions')}>
            <div className="flex flex-col gap-2 p-3">
              <textarea className="input w-full resize-none py-1.5" style={{ height: 64 }} placeholder={t('tickets.textPh')} value={text} onChange={(e) => setText(e.target.value)} />
              <div className="flex flex-wrap gap-1.5">
                <button className="btn btn-sm" disabled={act.isPending || closed || d.incident_status === 'in_progress'} onClick={() => act.mutate({ action: 'take', reason: text || undefined })}>
                  {t('tickets.act.take')}
                </button>
                <button className="btn btn-sm" disabled={act.isPending || closed || !text.trim() || !d.primary_client_id} title={!d.primary_client_id ? t('tickets.noClient') : undefined} onClick={() => act.mutate({ action: 'reply_client', text, channel_code: d.channel ?? 'chat' })}>
                  {t('tickets.act.reply')}
                </button>
                <button className="btn btn-sm" disabled={act.isPending || closed || !text.trim() || !d.primary_client_id} onClick={() => act.mutate({ action: 'request_client_data', text, channel_code: d.channel ?? 'chat' })}>
                  {t('tickets.act.requestData')}
                </button>
                <select className="input h-7 text-xs" value={team} onChange={(e) => setTeam(e.target.value)}>
                  <option value="">{t('tickets.chooseTeam')}</option>
                  {(teams.data ?? []).filter((tm) => tm.code !== d.department).map((tm) => (
                    <option key={tm.code} value={tm.code}>
                      {tm.name_ru}
                    </option>
                  ))}
                </select>
                <button className="btn btn-sm" disabled={act.isPending || closed || !team} onClick={() => act.mutate({ action: 'reroute', team_code: team, reason: text || undefined })}>
                  {t('tickets.act.reroute')}
                </button>
                <button className="btn btn-sm" disabled={esc.isPending || closed || text.trim().length < 3} onClick={() => esc.mutate({ incident_id: d.incident_id, reason: text, severity: d.criticality === 'high' ? 'critical' : 'high', actor: 'operator' })}>
                  {t('tickets.act.escalate')}
                </button>
                <button className="btn btn-sm btn-primary" disabled={act.isPending || closed} onClick={() => act.mutate({ action: 'close', text: text || undefined })}>
                  {t('tickets.act.close')}
                </button>
                <button className="btn btn-sm" disabled={act.isPending || closed} onClick={() => act.mutate({ action: 'reject', reason: text || undefined })}>
                  {t('tickets.act.reject')}
                </button>
              </div>
              {(act.error || esc.error) && <ErrorBox error={act.error ?? esc.error} compact />}
              {(act.isSuccess || esc.isSuccess) && <div className="text-xs text-ok">{t('tickets.done')}</div>}
            </div>
          </Section>

          {(d.escalations ?? []).length > 0 && (
            <Section title={t('tickets.view.escalations')}>
              <ul className="divide-y divide-line">
                {(d.escalations ?? []).map((e) => (
                  <li key={e.id} className="flex cursor-pointer items-center gap-2 px-3 py-1.5 text-sm hover:bg-raised" onClick={() => onOpenEsc(e.id ?? 0)}>
                    <span className="num font-mono text-xs text-muted">{e.public_id}</span>
                    <Badge tone={severityTone(e.severity)}>{tEnum('incident.severity', e.severity)}</Badge>
                    <span className="truncate">{tEnum('tickets.escReason', e.reason)}</span>
                    <Badge tone={e.status === 'open' ? 'danger' : e.status === 'acknowledged' ? 'warn' : 'neutral'} className="ml-auto">
                      {t(`tickets.escStatus.${e.status ?? 'open'}`)}
                    </Badge>
                  </li>
                ))}
              </ul>
            </Section>
          )}

          <Section title={t('tickets.history')}>
            <ul className="divide-y divide-line">
              {(d.history ?? []).map((h, i) => (
                <li key={i} className="flex items-start gap-2 px-3 py-1.5 text-xs">
                  <span className="num w-20 shrink-0 text-muted">{fmtSim(h.changed_sim)}</span>
                  <span className="shrink-0">
                    {tEnum('incident.status', h.from_status)} → <b>{tEnum('incident.status', h.to_status)}</b>
                  </span>
                  <Badge tone={h.actor_type === 'human' ? 'info' : 'neutral'}>{t(`tickets.actor.${h.actor_type ?? 'agent'}`)}</Badge>
                  <span className="min-w-0 flex-1 truncate text-muted" title={h.reason ?? ''}>
                    {h.reason}
                  </span>
                </li>
              ))}
              {(d.history ?? []).length === 0 && <li className="px-3 py-2 text-xs text-muted">{t('common.empty')}</li>}
            </ul>
          </Section>

          {d.decision_chain && (
            <Section
              title={t('tickets.chain')}
              right={
                <a className="btn btn-sm" href={`/api/agent/runs/${d.agent_run_id}/decision-chain?format=markdown`} target="_blank" rel="noreferrer">
                  Markdown
                </a>
              }
            >
              <ol className="divide-y divide-line">
                {(d.decision_chain.steps ?? []).map((s, i) => (
                  <li key={i} className="flex items-start gap-2 px-3 py-1.5 text-xs">
                    <span className="num w-5 shrink-0 text-muted">{s.step}</span>
                    <span className="shrink-0 font-mono">{s.tool ?? s.node}</span>
                    {s.wraps?.includes('side_effect') && <Badge tone="warn">{t('tickets.sideEffect')}</Badge>}
                    <span className="min-w-0 flex-1 text-muted">{s.why_ru}</span>
                  </li>
                ))}
              </ol>
            </Section>
          )}
        </div>
      )}
    </Drawer>
  )
}

function EscDrawer({ id, onClose }: { id: number | null; onClose: () => void }) {
  const { t } = useTranslation()
  const q = useEscalation(id)
  const d = q.data
  return (
    <Drawer open={id !== null} onClose={onClose} title={d ? `${d.public_id} · ${tEnum('tickets.escReason', d.reason)}` : '…'}>
      {q.error && <ErrorBox error={q.error} />}
      {d && (
        <div className="flex flex-col gap-3 p-3">
          <div className="divide-y divide-line">
            <KV k={t('tickets.col.status')} v={t(`tickets.escStatus.${d.status ?? 'open'}`)} />
            <KV k={t('incident.severityLabel')} v={tEnum('incident.severity', d.severity)} />
            <KV k={t('tickets.role.label')} v={t(`tickets.role.${d.to_role ?? 'cx_lead'}`)} />
            <KV k={t('tickets.createdBy')} v={t(`tickets.by.${d.created_by ?? 'agent'}`)} />
            {d.ticket_id && <KV k={t('tickets.col.ticket')} v={<Link to={`/incidents/${d.incident_id}`} className="font-mono hover:text-brand">{d.ticket_id}</Link>} />}
            {d.acknowledged_by && <KV k={t('tickets.ackBy', { who: '' })} v={`${d.acknowledged_by} · ${fmtSim(d.acknowledged_at)}`} />}
            {d.resolution_ru && <KV k={t('tickets.resolution')} v={d.resolution_ru} />}
          </div>
          {d.signal && (
            <Section title={t('tickets.signal')}>
              <div className="p-3 text-sm">
                <div className="mb-1 flex items-center gap-2 text-xs text-muted">
                  <span className="font-mono">{d.signal.public_id}</span>
                  <span>{tEnum('channel', d.signal.channel_code)}</span>
                  <span>{fmtSim(d.signal.received_sim)}</span>
                </div>
                <p className="whitespace-pre-wrap leading-relaxed">{d.signal.text}</p>
              </div>
            </Section>
          )}
          {d.decision_chain && (
            <Section title={t('tickets.chain')}>
              <ol className="divide-y divide-line">
                {(d.decision_chain.steps ?? []).map((s, i) => (
                  <li key={i} className="flex items-start gap-2 px-3 py-1.5 text-xs">
                    <span className="num w-5 shrink-0 text-muted">{s.step}</span>
                    <span className="shrink-0 font-mono">{s.tool ?? s.node}</span>
                    <span className="min-w-0 flex-1 text-muted">{s.why_ru}</span>
                  </li>
                ))}
              </ol>
            </Section>
          )}
        </div>
      )}
    </Drawer>
  )
}
