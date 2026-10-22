import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { clsx } from 'clsx'
import { useGifts, useTaskDecision, useTasks } from '@/shared/api/hooks'
import type { TaskItem } from '@/shared/api/client'
import { Badge, Empty, ErrorBox, Modal, SkeletonRows } from '@/shared/ui'
import { incidentStatusTone, type Tone } from '@/shared/ui/tones'
import { fmtSim } from '@/shared/lib/format'
import { tEnum } from '@/shared/i18n'

type Filter = 'all' | 'open' | 'ready' | 'done' | 'rejected'

const STATUS_TONE: Record<TaskItem['status'], Tone> = { open: 'info', approved: 'ok', changed: 'ok', rejected: 'danger', done: 'ok', cancelled: 'neutral' }

export function TasksTab({ runId }: { runId: number | undefined }) {
  const { t } = useTranslation()
  const [filter, setFilter] = useState<Filter>('open')
  const [changeId, setChangeId] = useState<number | null>(null)
  const query = useMemo(() => {
    const q: Record<string, string | number | boolean> = { limit: 200 }
    if (runId !== undefined) q.run_id = runId
    if (filter === 'open') q.status = 'open'
    if (filter === 'ready') {
      q.status = 'open'
      q.ready = true
    }
    if (filter === 'done') q.status = 'done'
    if (filter === 'rejected') q.status = 'rejected'
    return q
  }, [filter, runId])
  const q = useTasks(query)
  const decide = useTaskDecision()
  const items = q.data?.items ?? []
  const counts = q.data?.counts ?? {}
  const sum = (st: string) => Object.entries(counts).filter(([k]) => k.endsWith(`:${st}`)).reduce((a, [, v]) => a + v, 0)
  const ready = items.filter((x) => x.status === 'open' && x.ready && !x.requires_hitl)
  const changing = items.find((x) => x.id === changeId) ?? null

  const approveAll = async () => {
    for (const x of ready) await decide.mutateAsync({ id: x.id, action: 'approve' })
  }

  return (
    <div className="p-3">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <div className="mr-auto text-sm text-muted">{t('tasks.subtitle')}</div>
        {(['open', 'ready', 'done', 'rejected', 'all'] as Filter[]).map((f) => (
          <button key={f} className={clsx('chip', filter === f && 'chip-on')} onClick={() => setFilter(f)}>
            {t(`tasks.filter.${f}`)}
          </button>
        ))}
        {ready.length > 0 && (
          <button className="btn btn-sm btn-primary" disabled={decide.isPending} onClick={() => void approveAll()}>
            {t('tasks.approveReady', { n: ready.length })}
          </button>
        )}
      </div>
      <div className="mb-2 text-xs text-muted">{t('tasks.counts', { open: sum('open'), ready: items.filter((x) => x.ready && x.status === 'open').length, done: sum('done') })}</div>
      {q.error && <ErrorBox error={q.error} compact />}
      {decide.error && <ErrorBox error={decide.error} compact />}
      {q.isLoading && <SkeletonRows n={6} />}
      {!q.isLoading && items.length === 0 && <Empty title={t('common.empty')} />}
      {items.length > 0 && (
        <table className="card w-full text-sm">
          <thead className="text-left text-[11px] uppercase tracking-wide text-muted">
            <tr className="border-b border-line">
              <th className="px-3 py-1.5 font-medium">{t('tasks.col.task')}</th>
              <th className="px-3 py-1.5 font-medium">{t('tasks.col.client')}</th>
              <th className="px-3 py-1.5 font-medium">{t('tasks.col.incident')}</th>
              <th className="px-3 py-1.5 font-medium">{t('tasks.col.when')}</th>
              <th className="px-3 py-1.5 font-medium">{t('tasks.col.status')}</th>
              <th className="px-3 py-1.5 text-right font-medium">{t('tasks.col.actions')}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {items.map((x) => {
              const gift = x.payload.gift
              const label = x.kind === 'gift' ? (gift?.gift_code === 'bonus_points' && gift.points ? t('tasks.pointsN', { n: gift.points }) : (x.gift_name ?? gift?.gift_code ?? '')) : ''
              const open = x.status === 'open'
              return (
                <tr key={x.id} className={clsx(x.overdue && 'bg-danger/5')}>
                  <td className="px-3 py-1.5">
                    <div className="flex items-center gap-1.5">
                      <Badge tone="neutral">{t(`tasks.kind.${x.kind}`)}</Badge>
                      <span className="font-medium">{label}</span>
                    </div>
                    <div className="text-[11px] text-muted">
                      #{x.id} · {x.assignee} · {fmtSim(x.created_sim)}
                      {x.payload.issued && <> · {t('tasks.issued', { label: x.payload.issued.label })}</>}
                      {x.payload.decision?.comment && <> · {x.payload.decision.comment}</>}
                    </div>
                  </td>
                  <td className="px-3 py-1.5">
                    {x.client ? (
                      <>
                        <div>{x.client.display_name}</div>
                        <div className="text-[11px] text-muted">{x.client.segment_code} · {x.client.city_name}</div>
                      </>
                    ) : (
                      '—'
                    )}
                  </td>
                  <td className="px-3 py-1.5">
                    {x.incident_public_id ? (
                      <>
                        <div className="font-mono text-xs">{x.incident_public_id}</div>
                        <div className="flex items-center gap-1 text-[11px] text-muted">
                          <Badge tone={incidentStatusTone(x.incident_status)}>{tEnum('incident.status', x.incident_status)}</Badge>
                          <span className="truncate">{x.incident_title}</span>
                        </div>
                      </>
                    ) : (
                      '—'
                    )}
                  </td>
                  <td className="px-3 py-1.5 text-xs">
                    <div>{t(`tasks.when.${(gift?.when ?? (x.payload.when as string | undefined) ?? 'now') === 'after_resolved' ? 'after_resolved' : 'now'}`)}</div>
                    {open && (
                      <div className="mt-0.5 flex flex-wrap gap-1">
                        {x.ready ? <Badge tone="ok">{t('tasks.ready')}</Badge> : <Badge tone="neutral">{t('tasks.waiting')}</Badge>}
                        {x.requires_hitl && <Badge tone="warn">{t('tasks.hitl')}</Badge>}
                        {x.overdue && <Badge tone="danger">{t('tasks.overdue')}</Badge>}
                      </div>
                    )}
                  </td>
                  <td className="px-3 py-1.5">
                    <Badge tone={STATUS_TONE[x.status]}>{t(`tasks.status.${x.status}`)}</Badge>
                  </td>
                  <td className="px-3 py-1.5 text-right">
                    {open && (
                      <div className="flex justify-end gap-1">
                        <button className="btn btn-sm btn-primary" disabled={decide.isPending} onClick={() => decide.mutate({ id: x.id, action: x.kind === 'gift' ? 'approve' : 'done' })}>
                          {t(x.kind === 'gift' ? 'tasks.approve' : 'tasks.done')}
                        </button>
                        {x.kind === 'gift' && (
                          <button className="btn btn-sm" onClick={() => setChangeId(x.id)}>
                            {t('tasks.change')}
                          </button>
                        )}
                        <button className="btn btn-sm btn-ghost" disabled={decide.isPending} onClick={() => decide.mutate({ id: x.id, action: 'reject' })}>
                          {t('tasks.reject')}
                        </button>
                      </div>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
      <ChangeGiftModal task={changing} onClose={() => setChangeId(null)} />
    </div>
  )
}

function ChangeGiftModal({ task, onClose }: { task: TaskItem | null; onClose: () => void }) {
  const { t } = useTranslation()
  const gifts = useGifts()
  const decide = useTaskDecision()
  const [code, setCode] = useState<string>('')
  const [points, setPoints] = useState<string>('')
  const [comment, setComment] = useState('')
  const seg = task?.client?.segment_code
  const options = (gifts.data ?? []).filter((g) => !seg || !g.segments || g.segments.includes(seg))
  const cur = code || task?.payload.gift?.gift_code || options[0]?.code || ''
  const submit = async () => {
    if (!task) return
    const payload: Record<string, unknown> = { gift_code: cur }
    if (cur === 'bonus_points') payload.points = Number(points || task.payload.gift?.points || 300)
    await decide.mutateAsync({ id: task.id, action: 'change', payload, comment: comment || undefined })
    setCode('')
    setPoints('')
    setComment('')
    onClose()
  }
  return (
    <Modal open={!!task} onClose={onClose} title={t('tasks.changeTitle')}>
      {task && (
        <div className="space-y-3 text-sm">
          <div className="text-xs text-muted">
            {task.client?.display_name} · {task.client?.segment_code} · {task.incident_public_id}
          </div>
          <label className="block">
            <div className="mb-1 text-xs text-muted">{t('tasks.gift')}</div>
            <select className="input w-full" value={cur} onChange={(e) => setCode(e.target.value)}>
              {options.map((g) => (
                <option key={g.code} value={g.code}>
                  {g.name_ru}
                </option>
              ))}
            </select>
          </label>
          {cur === 'bonus_points' && (
            <label className="block">
              <div className="mb-1 text-xs text-muted">{t('tasks.points')}</div>
              <input className="input w-full" type="number" min={100} step={100} value={points || String(task.payload.gift?.points ?? 300)} onChange={(e) => setPoints(e.target.value)} />
            </label>
          )}
          <label className="block">
            <div className="mb-1 text-xs text-muted">{t('tasks.comment')}</div>
            <input className="input w-full" value={comment} onChange={(e) => setComment(e.target.value)} />
          </label>
          {decide.error && <ErrorBox error={decide.error} compact />}
          <div className="flex justify-end gap-2">
            <button className="btn btn-sm" onClick={onClose}>
              {t('common.close')}
            </button>
            <button className="btn btn-sm btn-primary" disabled={decide.isPending} onClick={() => void submit()}>
              {t('tasks.save')}
            </button>
          </div>
        </div>
      )}
    </Modal>
  )
}
