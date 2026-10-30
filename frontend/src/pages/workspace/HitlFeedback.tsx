import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { post, type Schemas } from '@/shared/api/client'
import { useHitlFeedback } from '@/shared/api/hooks'
import { ErrorBox } from '@/shared/ui'
import { fmtSim } from '@/shared/lib/format'
import { IdLink } from '@/shared/components/IdLink'

export function HitlFeedback({ id, comment, onComment }: { id: number; comment: string; onComment: (value: string) => void }) {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const history = useHitlFeedback(id)
  const [attempt, setAttempt] = useState<{ comment: string; key: string } | null>(null)
  const save = useMutation({
    mutationFn: (body: { comment: string; idempotency_key: string }) => post<Schemas['HitlFeedback']>(`/api/hitl/${id}/feedback`, body),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ['hitl'] }) },
  })
  return <section className="card space-y-3 p-3">
    <h3 className="font-semibold">{t('continuity.feedback')}</h3>
    <p className="text-xs text-muted">{t('continuity.feedbackHint')}</p>
    <form className="space-y-2" onSubmit={e => {
      e.preventDefault()
      const text = comment.trim()
      if (!text) return
      const key = attempt?.comment === text ? attempt.key : crypto.randomUUID()
      setAttempt({ comment: text, key })
      save.mutate({ comment: text, idempotency_key: key })
    }}>
      <label className="block text-xs">{t('continuity.information')}<textarea className="input mt-1 min-h-24 w-full py-2" maxLength={4000} required value={comment} onChange={e => { onComment(e.target.value); save.reset() }} /></label>
      <button className="btn btn-primary" disabled={!comment.trim() || save.isPending}>{t('continuity.sendInformation')}</button>
      {save.error && <ErrorBox error={save.error} />}
      {save.isSuccess && <p role="status" className="text-xs text-ok">{t('continuity.saved')}</p>}
    </form>
    {history.error && <ErrorBox error={history.error} />}
    <ul className="space-y-2">{history.data?.pages.flatMap(p => p.items).map(f => <li className="rounded border border-line p-2" key={f.id}><p className="whitespace-pre-wrap break-words text-sm">{f.comment}</p><p className="mt-1 text-xs text-muted">{t(f.processing_status === 'applied' ? 'continuity.feedbackApplied' : f.processing_status === 'failed' ? 'continuity.feedbackFailed' : 'continuity.feedbackPending')}</p>{f.review_run_ref && <IdLink kind="agent_run" value={f.review_run_ref}/>} {f.review?.summary_ru && <p className="mt-1 text-sm">{f.review.summary_ru}</p>}<p className="mt-1 text-xs text-muted">{f.recorded_by} · {fmtSim(f.recorded_at)}</p></li>)}</ul>
    {history.hasNextPage && <button className="btn btn-sm" disabled={history.isFetchingNextPage} onClick={() => void history.fetchNextPage()}>{t('continuity.more')}</button>}
  </section>
}
