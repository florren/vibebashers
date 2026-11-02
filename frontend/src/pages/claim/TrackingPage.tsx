import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { ApiError, api, type Schemas } from '@/shared/api/client'
import { fmtSim } from '@/shared/lib/format'

type Tracking = Schemas['TrackingView']

export function TrackingPage() {
  const { token = '' } = useParams()
  const { t, i18n } = useTranslation()
  const qc = useQueryClient()
  const [text, setText] = useState('')
  const [notice, setNotice] = useState('')
  const previous = useRef<{ token: string; ids: Set<number> }>()
  const requestKey = useRef<{ token: string; text: string; id: string }>()
  const valid = /^[A-Za-z0-9_-]{24,}$/.test(token)
  const key = ['public-tracking', token, i18n.language]
  const query = useQuery({
    queryKey: key,
    queryFn: () => api<Tracking>(`/api/public/track/${encodeURIComponent(token)}`, { headers: { 'Accept-Language': i18n.language } }),
    enabled: valid,
    retry: false,
    gcTime: 0,
    refetchInterval: 10_000,
  })
  const append = useMutation({
    mutationFn: (value: string) => {
      if (requestKey.current?.token !== token || requestKey.current.text !== value) requestKey.current = { token, text: value, id: crypto.randomUUID() }
      return api<void>(`/api/public/track/${encodeURIComponent(token)}`, { method: 'POST', body: JSON.stringify({ text: value }), headers: { 'Idempotency-Key': requestKey.current.id } })
    },
    onSuccess: () => {
      setText('')
      requestKey.current = undefined
      setNotice(t('tracking.appended'))
      void qc.invalidateQueries({ queryKey: ['public-tracking', token] })
    },
  })
  const data = query.data
  const resetAppend = append.reset
  const notes = (data?.notifications ?? []).filter(note => note.status === 'sent' || note.status === 'delivered')
  const notFound = !valid || (query.error instanceof ApiError && query.error.status === 404)
  useEffect(() => {
    setText('')
    setNotice('')
    resetAppend()
    // Форму и уведомления другого обращения не переносим при смене ссылки.
  }, [token, resetAppend])
  useEffect(() => {
    if (!data) return
    const ids = new Set((data.notifications ?? []).flatMap(note => note.id == null || !['sent', 'delivered'].includes(note.status ?? '') ? [] : [note.id]))
    if (previous.current?.token === token && [...ids].some(id => !previous.current!.ids.has(id))) setNotice(t('tracking.newMessage'))
    previous.current = { token, ids }
  }, [data, token, t])
  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (data?.can_append && text.trim() && !append.isPending) append.mutate(text.trim())
  }
  if (notFound) return <section className="mx-auto max-w-2xl space-y-3 p-5"><h1 className="text-xl font-semibold">{t('tracking.notFound')}</h1><p>{t('tracking.checkLink')}</p><Link className="btn" to="/claim">{t('tracking.newClaim')}</Link></section>
  return <div className="mx-auto max-w-2xl space-y-5 p-4">
    <header><h1 className="text-xl font-semibold">{t('tracking.title')}</h1><p className="mt-1 text-sm text-muted">{t('tracking.privateLink')}</p></header>
    <p role="status" aria-live="polite">{notice}</p>
    {query.isPending && <p role="status">{t('tracking.loading')}</p>}
    {query.isError && <section role="alert" className="card space-y-2 p-4"><p>{t('tracking.loadError')}</p><button className="btn" onClick={() => void query.refetch()}>{t('tracking.retry')}</button></section>}
    {data && <>
      <section className="card space-y-3 p-4" aria-label={t('tracking.history')}>
        <p className="font-mono font-semibold">{data.public_id}</p>
        <h2 className="font-semibold">{t('tracking.history')}</h2>
        <ol className="space-y-3">
          {(data.timeline ?? []).map(step => <li key={step.step} className="flex gap-3 border-b border-line pb-3 last:border-0">
            <span aria-hidden className={step.done ? 'text-brand' : 'text-muted'}>{step.done ? '✓' : '○'}</span>
            <div><p className={step.done ? 'font-medium' : 'text-muted'}>{t(`tracking.steps.${step.step}`)}<span className="sr-only"> — {t(step.done ? 'tracking.done' : 'tracking.pending')}</span></p>
              {step.done && step.at_sim && <time dateTime={step.at_sim} className="text-xs text-muted">{fmtSim(step.at_sim)}</time>}
              {step.done && step.text_ru && <p className="mt-1 whitespace-pre-wrap text-sm">{step.text_ru}</p>}
            </div>
          </li>)}
        </ol>
        <p className="text-xs text-muted">{t('tracking.refreshHint')}</p>
      </section>
      <section className="card space-y-3 p-4" aria-label={t('tracking.messages')}>
        <h2 className="font-semibold">{t('tracking.messages')}</h2>
        {!notes.length && <p className="text-sm text-muted">{t('tracking.noMessages')}</p>}
        <ul className="space-y-3" aria-live="polite" aria-relevant="additions">
          {notes.map(note => <li key={note.id} className="rounded-lg border border-line p-3">
            {note.subject && <h3 className="font-medium">{note.subject}</h3>}
            <p className="whitespace-pre-wrap text-sm">{note.body}</p>
            {note.sent_sim && <time dateTime={note.sent_sim} className="mt-2 block text-xs text-muted">{fmtSim(note.sent_sim)}</time>}
          </li>)}
        </ul>
      </section>
      {data.can_append && <section className="card space-y-3 p-4">
        <h2 className="font-semibold">{t('tracking.appendTitle')}</h2>
        {data.question_from_agent && <p className="whitespace-pre-wrap">{data.question_from_agent}</p>}
        <form onSubmit={submit} className="space-y-3">
          <label className="block text-sm">{t('tracking.reply')}<textarea className="input mt-1 w-full" rows={4} maxLength={4000} value={text} onChange={event => setText(event.target.value)} /></label>
          <p className="text-xs text-muted">{t('claim.fictionalHint')}</p>
          {append.isError && <p role="alert" className="text-sm text-danger">{t('tracking.appendError')}</p>}
          <button className="btn btn-primary" disabled={!text.trim() || append.isPending}>{t(append.isPending ? 'tracking.sending' : 'tracking.send')}</button>
        </form>
      </section>}
    </>}
  </div>
}
