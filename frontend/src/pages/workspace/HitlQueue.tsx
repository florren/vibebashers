import { IdLink } from '@/shared/components/IdLink'
import { clsx } from 'clsx'
import { Check, Pencil, Users, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router-dom'
import type { Decision, HitlItem } from '@/shared/api/client'
import { useHitlDecide, useHitlItem, useHitlPages, useRefName, useRefs } from '@/shared/api/hooks'
import { tEnum } from '@/shared/i18n'
import { fmtSim } from '@/shared/lib/format'
import { Badge, Empty, ErrorBox, SkeletonRows } from '@/shared/ui'
import { criticalityTone, severityTone } from '@/shared/ui/tones'
import { HitlFeedback } from './HitlFeedback'
import { DecisionView } from './SignalDrawer'

type Mode = 'accept' | 'modify' | 'reject' | 'delegate'

export function HitlQueue({ runId, onOpenSignal }: { runId: number | undefined; onOpenSignal: (id: number) => void }) {
  const { t } = useTranslation()
  const [params, setParams] = useSearchParams()
  const incoming = (params.get('q') ?? '').slice(0, 200)
  const [search, setSearch] = useState(incoming)
  const [scope, setScope] = useState<'all' | 'current'>('all')
  const [history, setHistory] = useState(false)
  const q = useHitlPages({ run_id: scope === 'all' ? 'all' : runId ?? 'current', q: search || undefined, include_decided: history })
  const [selected, setSelected] = useState<number | null>(null)
  useEffect(() => { if (incoming) { setSearch(incoming); setSelected(null) } }, [incoming])
  const items = q.data?.pages.flatMap(p => p.items ?? []) ?? []
  const first = items[0]?.id
  useEffect(() => { if (selected === null && first !== undefined) setSelected(first) }, [first, selected])
  const detail = useHitlItem(selected)
  const current = detail.data ?? items.find(i => i.id === selected) ?? (selected === null ? items[0] : null) ?? null

  return (
    <div className="flex h-full flex-col overflow-y-auto lg:flex-row lg:overflow-hidden">
      <aside className="max-h-[45vh] w-full shrink-0 overflow-y-auto border-b border-line lg:max-h-none lg:w-80 lg:border-r">
        <div className="sticky top-0 z-10 space-y-2 border-b border-line bg-panel p-3">
          <label className="block text-xs">{t('continuity.hitlSearch')}<input className="input mt-1 w-full" maxLength={200} value={search} onChange={e => { setSearch(e.target.value); setSelected(null); if (params.has('q')) setParams(p => { p.delete('q'); return p }, { replace: true }) }} placeholder="SIG, INC, HD, ESC, AR, CL, TSK…" /></label>
          <label className="block text-xs">{t('continuity.scope')}<select className="input mt-1 w-full" value={scope} onChange={e => { setScope(e.target.value as typeof scope); setSelected(null) }}><option value="all">{t('continuity.allRuns')}</option><option value="current">{t('continuity.currentRun')}</option></select></label>
          <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={history} onChange={e => { setHistory(e.target.checked); setSelected(null) }} />{t('continuity.includeDecided')}</label>
          <p className="text-xs text-muted">{t('continuity.searchHint')}</p>
        </div>
        {(q.data?.pages[0]?.related_entities?.length ?? 0) > 0 && <section className="space-y-2 border-b border-line p-3" aria-label={t('continuity.related')}><h3 className="text-xs font-semibold">{t('continuity.related')}</h3><div className="flex flex-wrap gap-2">{q.data?.pages[0]?.related_entities?.map(e => <IdLink key={`${e.kind}:${e.ref}`} kind={e.kind} value={e.ref} />)}</div>{q.data?.pages[0]?.related_entities_truncated && <p className="text-xs text-muted">{t('continuity.relatedLimit')}</p>}</section>}
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
                <div className="mb-1 break-words font-mono text-xs text-info">{it.signal?.public_id ?? it.public_id}{it.incident?.public_id && ` → ${it.incident.public_id}`}</div>
                <div className="line-clamp-2 text-[13px]">{it.signal?.text}</div>
                <div className="mt-1 truncate text-xs text-muted">
                  {it.signal?.client?.display_name ?? t('common.anonymous')} · {tEnum('channel', it.signal?.channel_code)} · {fmtSim(it.requested_sim)}
                </div>
              </button>
            </li>
          ))}
        </ul>
        {q.hasNextPage && <button className="btn m-3" disabled={q.isFetchingNextPage} onClick={() => void q.fetchNextPage()}>{t('continuity.more')}</button>}
      </aside>
      <div className="min-w-0 shrink-0 lg:min-h-0 lg:flex-1 lg:overflow-y-auto">
        {detail.error && <ErrorBox error={detail.error} />}
        {current ? <HitlCard key={current.id} item={current} onOpenSignal={onOpenSignal} /> : q.data && <Empty title={t(q.data?.pages[0]?.related_entities?.length ? 'continuity.noRequest' : 'hitl.empty')} />}
      </div>
    </div>
  )
}

export function HitlCard({ item, onOpenSignal }: { item: HitlItem; onOpenSignal: (id: number) => void }) {
  const { t } = useTranslation()
  const team = useRefName('teams')
  const teams = useRefs('teams')
  const decide = useHitlDecide()
  const [mode, setMode] = useState<Mode>('accept')
  const [comment, setComment] = useState('')
  const [fewshot, setFewshot] = useState(false)
  const [delegateTo, setDelegateTo] = useState('')
  const p = item.agent_proposal && 'incident_action' in item.agent_proposal ? item.agent_proposal as Decision : undefined
  const canResume = item.can_resume ?? !item.decision
  const preparing = item.agent_run_id != null && item.process_outcome == null && !(item.agent_proposal && 'kind' in item.agent_proposal && item.agent_proposal.kind === 'escalation')
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

        </div>
        <div className="flex flex-wrap items-center gap-2 rounded border border-line p-2" aria-label={t('continuity.lineage')}>
          <IdLink kind="signal" value={item.signal?.public_id} /><span>→</span>
          {(item.related_incidents ?? (item.incident ? [item.incident] : [])).map(inc => <IdLink key={inc.id} kind="incident" value={inc.public_id} />)}
          <IdLink kind="human_decision" value={item.public_id} />
          {item.run_public_id && <IdLink kind="sim_run" value={item.run_public_id} />}
          {(item.escalations ?? []).map(e => <IdLink key={e.ref} kind={e.kind} value={e.ref} />)}
        </div>
        <p className="text-xs text-muted">{t(canResume ? 'continuity.waitingGraph' : 'continuity.progressed')} · {item.process_outcome ?? '—'}</p>
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
      <div className="space-y-4 xl:sticky xl:top-4 xl:self-start">
        {item.decision ? (
          <div className="rounded-lg border border-ok/30 bg-ok/5 p-3 text-sm text-ok">
            {t(item.automatic_decision ? 'continuity.automatic' : 'hitl.decided')}: {item.decision} · {item.decided_by}
            {item.comment && <p className="mt-2 whitespace-pre-wrap break-words">{item.comment}</p>}
          </div>
        ) : !canResume ? (
          <div className="card space-y-3 p-3"><p className="text-sm">{t(preparing ? 'continuity.preparing' : 'continuity.contextRequest')}</p>
            {decide.error && <ErrorBox error={decide.error} />}
            <button className="btn" disabled={decide.isPending || preparing} onClick={() => item.id !== undefined && decide.mutate({ id: item.id, body: { decision: 'accept', use_as_fewshot: false } })}>{t('continuity.acknowledge')}</button>
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
        {item.id !== undefined && <HitlFeedback id={item.id} comment={comment} onComment={setComment} />}
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
