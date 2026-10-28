import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { getJourney } from '@/shared/api/trace'
import { IdLink } from '@/shared/components/IdLink'
import { EventCard } from '@/pages/trace/components/EventCard'

export function JourneyPage() {
  const { ref } = useParams()
  const { t } = useTranslation()
  const result = useQuery({ queryKey: ['journey', ref], queryFn: () => getJourney(ref) })
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [])
  const data = result.data
  return (
    <main className="h-full overflow-auto p-5">
      <h1 className="text-xl font-semibold">{t('journeyUi.title')}</h1>
      {result.isPending && <p role="status">{t('traceUi.loading')}</p>}
      {result.isError && (
        <p role="alert">
          {t('journeyUi.error')}{' '}
          <button className="btn" onClick={() => void result.refetch()}>
            {t('traceUi.retry')}
          </button>
        </p>
      )}
      {data && (
        <>
          <div className="my-4 flex items-center gap-3">
            <IdLink kind={data.subject.kind} value={data.subject.ref} />
            <h2>{data.subject.title_ru}</h2>
          </div>
          <div className="grid gap-5 lg:grid-cols-[2fr_1fr]">
            <section aria-label={t('journeyUi.bank')}>
              <h2 className="mb-3 font-semibold">{t('journeyUi.bank')}</h2>
              <ol>
                {data.stages.map((s, i) => {
                  const timestamps = s.events.map((e) => Date.parse(e.ts_sim ?? e.ts_real)).sort((a, b) => a - b)
                  const duration =
                    timestamps.length > 1
                      ? Math.max(0, Math.round(((timestamps[timestamps.length - 1] ?? 0) - (timestamps[0] ?? 0)) / 1000))
                      : 0
                  const requested = s.events.find((e) => e.kind === 'human_request')
                  return (
                    <li key={s.stage} className="my-3">
                      <details
                        key={`${ref}:${s.stage}:${s.status}`}
                        open={s.status === 'active' || s.status === 'waiting_human'}
                        className="rounded-xl border border-line bg-surface p-4"
                      >
                        <summary className="cursor-pointer">
                          <strong>
                            {i + 1}. {t(`journeyUi.stage.${s.stage}`)}
                          </strong>{' '}
                          · {t(`journeyUi.status.${s.status}`)} · {t('journeyUi.events', { n: s.events.length })} ·{' '}
                          {t('journeyUi.seconds', { n: duration })}
                        </summary>
                        {s.status === 'waiting_human' && requested && (
                          <p role="timer" className="my-3 rounded border border-dashed border-line p-3">
                            ◷ {t('journeyUi.waiting', { n: Math.max(0, Math.floor((now - Date.parse(requested.ts_real)) / 1000)) })}
                          </p>
                        )}
                        {s.events.map((e) => (
                          <div key={e.id}>
                            <EventCard event={e} />
                            <dl className="text-xs">
                              {e.key_facts.map((f, j) => (
                                <div key={j}>
                                  {f.label_ru}: {f.value_ru}
                                </div>
                              ))}
                            </dl>
                            <div className="flex gap-3 text-xs">
                              {e.links.engine_step && (
                                <Link className="text-brand" to={e.links.engine_step}>
                                  {t('traceUi.engine')}
                                </Link>
                              )}
                              {e.links.trace && (
                                <Link className="text-brand" to={e.links.trace}>
                                  {t('traceUi.title')}
                                </Link>
                              )}
                            </div>
                          </div>
                        ))}
                      </details>
                    </li>
                  )
                })}
              </ol>
            </section>
            <aside className="rounded-xl border border-line bg-raised p-4">
              <h2 className="font-semibold">{t('journeyUi.client')}</h2>
              <p className="mt-3 text-muted">{t('journeyUi.clientPlaceholder')}</p>
            </aside>
          </div>
          <footer className="sticky bottom-0 mt-5 flex flex-wrap gap-5 rounded-xl border border-brand bg-surface p-4">
            <strong>{data.summary.outcome_ru}</strong>
            <span>
              {data.summary.amount_rub != null
                ? new Intl.NumberFormat('ru-RU', { style: 'currency', currency: 'RUB' }).format(data.summary.amount_rub)
                : '—'}
            </span>
            <span>{data.summary.duration_sim}</span>
            <span className="rounded border border-line px-2">{data.summary.llm_source}</span>
            {data.stages
              .flatMap((s) => s.events)
              .flatMap((e) => e.key_facts)
              .filter((f) => f.label_ru === 'Первый ответ, с')
              .map((f, i) => (
                <span key={i}>
                  {t('journeyUi.firstReply')}: {f.value_ru} {t('journeyUi.sec')}
                </span>
              ))}
          </footer>
        </>
      )}
    </main>
  )
}
