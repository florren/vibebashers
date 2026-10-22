import { clsx } from 'clsx'
import { Check, Pencil, Users, X } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import type { Decision, HitlItem } from '@/shared/api/client'
import { useHitlDecide, useHitlQueue, useRefName, useRefs } from '@/shared/api/hooks'
import { tEnum } from '@/shared/i18n'
import { fmtSim } from '@/shared/lib/format'
import { Badge, Empty, ErrorBox, SkeletonRows } from '@/shared/ui'
import { criticalityTone, severityTone } from '@/shared/ui/tones'
import { DecisionView } from './SignalDrawer'

type Mode = 'accept' | 'modify' | 'reject' | 'delegate'

export function HitlQueue({ runId, onOpenSignal }: { runId: number | undefined; onOpenSignal: (id: number) => void }) {
  const { t } = useTranslation()
  const q = useHitlQueue({ run_id: runId })
  const [selected, setSelected] = useState<number | null>(null)
  const items = q.data?.items ?? []
  const current = items.find((i) => i.id === selected) ?? items[0] ?? null

  return (
    <div className="flex h-full">
      <aside className="w-80 shrink-0 overflow-y-auto border-r border-line">
        {q.isPending && <SkeletonRows n={4} />}
        {q.isError && <ErrorBox error={q.error} />}
        <ul className="divide-y divide-line">
          {items.map((it) => (
            <li key={it.id}>
              <button
                onClick={() => setSelected(it.id ?? null)}
                className={clsx('block w-full px-3 py-2.5 text-left transition hover:bg-raised', current?.id === it.id && 'bg-brand-soft/50')}
              >
                <div className="mb-1 flex items-center gap-1.5">
                  <Badge tone="warn">{tEnum('hitl.reason', it.reason)}</Badge>
                  {it.signal?.classification?.criticality && (
                    <Badge tone={criticalityTone(it.signal.classification.criticality)}>
                      {tEnum('incident.criticality', it.signal.classification.criticality)}
                    </Badge>
                  )}
                  <span className="ml-auto num text-[11px] text-muted">{t('hitl.waiting', { m: it.waiting_minutes ?? 0 })}</span>
                </div>
                <div className="line-clamp-2 text-[13px]">{it.signal?.text}</div>
                <div className="mt-1 truncate text-xs text-muted">
                  {it.signal?.client?.display_name ?? t('common.anonymous')} · {tEnum('channel', it.signal?.channel_code)} · {fmtSim(it.requested_sim)}
                </div>
              </button>
            </li>
          ))}
        </ul>
      </aside>
      <div className="min-w-0 flex-1 overflow-y-auto">
        {current ? <HitlCard key={current.id} item={current} onOpenSignal={onOpenSignal} /> : q.data && <Empty title={t('hitl.empty')} />}
      </div>
    </div>
  )
}

function HitlCard({ item, onOpenSignal }: { item: HitlItem; onOpenSignal: (id: number) => void }) {
  const { t } = useTranslation()
  const team = useRefName('teams')
  const teams = useRefs('teams')
  const decide = useHitlDecide()
  const [mode, setMode] = useState<Mode>('accept')
  const [comment, setComment] = useState('')
  const [fewshot, setFewshot] = useState(false)
  const [delegateTo, setDelegateTo] = useState('')
  const p = item.agent_proposal
  const [editTeam, setEditTeam] = useState(p?.route?.team ?? '')
  const [editPriority, setEditPriority] = useState(String(p?.priority ?? 3))
  const [editReply, setEditReply] = useState(p?.client_action?.text_ru ?? '')
  const c = item.signal?.classification

  const submit = () => {
    if (item.id === undefined) return
    const body: Parameters<typeof decide.mutate>[0]['body'] = { decision: mode, comment: comment || undefined, use_as_fewshot: fewshot || undefined }
    if (mode === 'modify') {
      const mp: Partial<Decision> = {}
      if (editTeam && editTeam !== p?.route?.team) mp.route = { ...(p?.route ?? {}), team: editTeam } as Decision['route']
      if (Number(editPriority) !== p?.priority) mp.priority = Number(editPriority) as Decision['priority']
      if (editReply !== (p?.client_action?.text_ru ?? '')) mp.client_action = { ...(p?.client_action ?? {}), text_ru: editReply } as Decision['client_action']
      body.modified_proposal = mp as Decision
    }
    if (mode === 'delegate') body.delegate_to = delegateTo || undefined
    decide.mutate({ id: item.id, body })
  }

  return (
    <div className="fade-in grid gap-4 p-4 xl:grid-cols-[minmax(0,1fr)_380px]">
      <div className="min-w-0 space-y-3">
        <div className="flex items-center gap-2">
          <Badge tone="warn">{tEnum('hitl.reason', item.reason)}</Badge>
          {c?.signal_type && <Badge tone="info">{tEnum('signal.type', c.signal_type)}</Badge>}
          {c?.problem_summary && <Badge tone={severityTone(c.problem_summary.severity)}>{tEnum('incident.severity', c.problem_summary.severity)}</Badge>}
          <span className="ml-auto text-xs text-muted">{t('hitl.waiting', { m: item.waiting_minutes ?? 0 })}</span>
          {item.signal?.id !== undefined && (
            <button className="btn btn-sm" onClick={() => onOpenSignal(item.signal!.id!)}>
              {t('jury.openSignal')}
            </button>
          )}
          {item.incident?.id !== undefined && (
            <Link className="btn btn-sm" to={`/incidents/${item.incident.id}`}>
              {item.incident.public_id}
            </Link>
          )}
        </div>
        <blockquote className="rounded-xl border-l-4 border-warn bg-raised p-3 text-[13.5px] leading-relaxed">{item.signal?.text}</blockquote>
        {item.context_summary_ru && (
          <div className="rounded-lg bg-raised p-3 text-[13px] leading-relaxed">
            <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">{t('hitl.context')}</div>
            {item.context_summary_ru}
          </div>
        )}
        {p && <DecisionView d={p} team={team} />}
        {item.recommendation && (
          <div className="rounded-lg border border-brand/30 bg-brand-soft/40 p-3 text-[13px]">
            <span className="font-medium">{t('hitl.recommendation')}:</span> {item.recommendation}
          </div>
        )}
      </div>
      <div className="xl:sticky xl:top-4 xl:self-start">
        {item.decision ? (
          <div className="rounded-lg border border-ok/30 bg-ok/5 p-3 text-sm text-ok">
            {t('hitl.decided')}: {item.decision} · {item.decided_by}
          </div>
        ) : (
          <div className="card p-3">
            <div className="mb-3 grid grid-cols-2 gap-1.5">
              <ModeBtn on={mode === 'accept'} onClick={() => setMode('accept')} icon={<Check size={14} />} label={t('hitl.accept')} tone="ok" />
              <ModeBtn on={mode === 'modify'} onClick={() => setMode('modify')} icon={<Pencil size={14} />} label={t('hitl.modify')} tone="info" />
              <ModeBtn on={mode === 'reject'} onClick={() => setMode('reject')} icon={<X size={14} />} label={t('hitl.reject')} tone="danger" />
              <ModeBtn on={mode === 'delegate'} onClick={() => setMode('delegate')} icon={<Users size={14} />} label={t('hitl.delegate')} tone="neutral" />
            </div>
            {(item.options?.length ?? 0) > 0 && (
              <div className="mb-3 flex flex-wrap gap-1.5">
                {item.options!.map((o) => (
                  <span key={o.code} className="chip" title={o.description_ru}>
                    {o.label_ru}
                  </span>
                ))}
              </div>
            )}
            {mode === 'modify' && (
              <div className="mb-3 grid grid-cols-2 gap-2">
                <label className="block">
                  <span className="mb-1 block text-xs text-muted">{t('hitl.editTeam')}</span>
                  <select className="input w-full" value={editTeam} onChange={(e) => setEditTeam(e.target.value)}>
                    {(teams.data ?? []).map((tm) => (
                      <option key={tm.code} value={tm.code}>
                        {tm.name_ru}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="block">
                  <span className="mb-1 block text-xs text-muted">{t('hitl.editPriority')}</span>
                  <select className="input w-full" value={editPriority} onChange={(e) => setEditPriority(e.target.value)}>
                    {[1, 2, 3, 4].map((n) => (
                      <option key={n} value={n}>
                        P{n}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="col-span-2 block">
                  <span className="mb-1 block text-xs text-muted">{t('hitl.editReply')}</span>
                  <textarea className="input h-24 w-full resize-y py-2" value={editReply} onChange={(e) => setEditReply(e.target.value)} />
                </label>
              </div>
            )}
            {mode === 'delegate' && (
              <label className="mb-3 block">
                <span className="mb-1 block text-xs text-muted">{t('hitl.delegateTo')}</span>
                <select className="input w-full" value={delegateTo} onChange={(e) => setDelegateTo(e.target.value)}>
                  <option value="">—</option>
                  {(teams.data ?? []).map((tm) => (
                    <option key={tm.code} value={tm.code}>
                      {tm.name_ru}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <label className="block">
              <span className="mb-1 block text-xs text-muted">{t('hitl.comment')}</span>
              <input className="input w-full" value={comment} onChange={(e) => setComment(e.target.value)} />
            </label>
            <div className="mt-3 flex items-center gap-3">
              <label className="flex items-center gap-1.5 text-xs text-muted">
                <input type="checkbox" checked={fewshot} onChange={(e) => setFewshot(e.target.checked)} /> {t('hitl.fewshot')}
              </label>
              <span className="mx-auto" />
              {decide.isError && <ErrorBox error={decide.error} compact />}
              <button className="btn btn-primary" onClick={submit} disabled={decide.isPending || (mode === 'delegate' && !delegateTo)}>
                {t('hitl.submit')}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function ModeBtn({
  on,
  onClick,
  icon,
  label,
  tone,
}: {
  on: boolean
  onClick: () => void
  icon: React.ReactNode
  label: string
  tone: 'ok' | 'info' | 'danger' | 'neutral'
}) {
  const ring = { ok: 'border-ok bg-ok/10', info: 'border-info bg-info/10', danger: 'border-danger bg-danger/10', neutral: 'border-ink/40 bg-raised' }[tone]
  return (
    <button
      onClick={onClick}
      className={clsx(
        'flex h-9 items-center justify-center gap-1.5 rounded-lg border text-[13px] font-medium transition',
        on ? ring : 'border-line hover:bg-raised',
      )}
    >
      {icon} {label}
    </button>
  )
}
