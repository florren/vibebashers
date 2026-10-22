import { useTranslation } from 'react-i18next'
import { useDeferred } from '@/shared/api/hooks'
import { fmtSim } from '@/shared/lib/format'
import { Badge, Empty, ErrorBox, SkeletonRows } from '@/shared/ui'

type Row = { followup_id?: number; signal_id?: number; incident_id?: number | null; wake_sim?: string; reason?: string; status?: string; text?: string }

export function DeferredList({ runId, onOpenSignal }: { runId: number | undefined; onOpenSignal: (id: number) => void }) {
  const { t } = useTranslation()
  const q = useDeferred({ run_id: runId, limit: 100 })
  const items = (q.data?.items ?? []) as Row[]
  return (
    <div className="h-full overflow-y-auto">
      {q.isPending && <SkeletonRows n={4} />}
      {q.isError && <ErrorBox error={q.error} />}
      {q.data && items.length === 0 && <Empty title={t('deferred.empty')} />}
      <ul className="divide-y divide-line">
        {items.map((r) => (
          <li key={r.followup_id}>
            <button
              className="flex w-full items-center gap-3 px-3 py-2 text-left hover:bg-raised"
              onClick={() => r.signal_id !== undefined && onOpenSignal(r.signal_id)}
            >
              <span className="num font-mono text-xs text-muted">
                {t('deferred.wake')} {fmtSim(r.wake_sim)}
              </span>
              <Badge tone={r.status === 'fired' ? 'ok' : 'info'}>{r.reason}</Badge>
              <span className="min-w-0 flex-1 truncate text-[13px]">{r.text}</span>
              {r.incident_id && <span className="font-mono text-xs text-muted">INC-{String(r.incident_id).padStart(6, '0')}</span>}
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}
