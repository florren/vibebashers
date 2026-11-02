import { useQuery } from '@tanstack/react-query'
import { api, type IncidentBrief } from '@/shared/api/client'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { useSimState } from '@/shared/api/hooks'
import { useWs } from '@/shared/ws/client'
import { SlaWarning } from './SlaWarning'

const ACTIVE = ['new', 'classified', 'routed', 'in_progress', 'fix_proposed', 'fix_deployed', 'awaiting_human', 'awaiting_client', 'verifying', 'escalated']
/** Только реальные приоритеты инцидентов текущего запуска; без таймера переключения и сырого текста. */
export function PriorityStrip() {
  const { t } = useTranslation()
  const sim = useSimState()
  const runId = useWs(s => s.sim?.current_run_id) ?? sim.data?.current_run_id ?? 'current'
  const [revision, setRevision] = useState(0)
  useEffect(() => useWs.subscribe((state, previous) => {
    if (state.events !== previous.events && state.events[0]?.topic === 'runs') setRevision(state.events[0].seq)
  }), [])
  const query = { run_id: runId, status: ACTIVE, sort: 'priority', limit: 3 }
  const list = useQuery({ queryKey: ['incidents', 'list', query, 'priorities', revision], queryFn: () => api<{ items?: IncidentBrief[] }>('/api/incidents', { query }), refetchInterval: 15_000 })
  const [selected, setSelected] = useState(0)
  const items = list.data?.items?.slice(0, 3) ?? []
  const index = Math.min(selected, Math.max(0, items.length - 1))
  const current = items[index]
  return <section className="priority-strip flex shrink-0 flex-wrap items-center gap-2 border-b border-line bg-surface px-3 py-1 text-sm" aria-label={t('attention.priorities')}>
    <span className="font-medium">{t('attention.priorities')}</span>
    {list.isError ? <span role="status">{t('care.errors.service')}</span> : !current ? <span className="text-muted">{t(list.isPending ? 'attention.loading' : 'attention.noPriorities')}</span> : <>
      <div className="flex gap-1" role="group" aria-label={t('attention.choosePriority')}>
        {items.map((item, n) => <button key={item.id} className="btn btn-sm" aria-pressed={index === n} aria-label={t('attention.chooseItem', { n: n + 1 })} onClick={() => setSelected(n)}>{n + 1}</button>)}
      </div>
      <Link className="font-mono text-sm text-info underline" to={`/incidents/${current.id}`}>{current.public_id} · P{current.priority ?? '—'}</Link>
      <SlaWarning due={current.sla_due_sim} status={current.status} />
    </>}
  </section>
}
