import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { getTrace, type Trace, type TraceEvent } from '@/shared/api/trace'
import { GlobalSearch } from '@/shared/components/GlobalSearch'
import { IdLink } from '@/shared/components/IdLink'
import { ROUTES } from '@/shared/routes'
import { EventCard } from './components/EventCard'
import { SubjectCard } from './components/SubjectCard'
import './trace.css'

export function TracePage() {
  const { kind, ref } = useParams()
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [details, setDetails] = useState<TraceEvent | null>(null)
  const [keyOnly, setKeyOnly] = useState(true)
  const [tab, setTab] = useState('subject')
  const result = useQuery({ queryKey: ['trace', kind, ref], queryFn: () => getTrace(kind!, ref!), enabled: !!kind && !!ref })
  const data = result.data
  const select = (e: TraceEvent) => setDetails(e)
  const beforeGroups = data?.groups.filter((g) => g.sample_refs.some((ref) => data.before.some((e) => e.object_ref?.ref === ref))) ?? []
  return (
    <main className="trace-page h-full overflow-auto p-4">
      <h1 className="text-xl font-semibold">{t('traceUi.title')}</h1>
      <GlobalSearch inline />
      {kind && ref && (
        <nav className="mb-3 flex items-center gap-3" aria-label={t('traceUi.breadcrumbs')}>
          <button className="btn" onClick={() => navigate(-1)}>
            {t('traceUi.back')}
          </button>
          <Link to={ROUTES.trace}>{t('traceUi.title')}</Link>
          <IdLink kind={kind} value={ref} />
        </nav>
      )}
      {result.isFetching && <p role="status">{t('traceUi.loading')}</p>}
      {result.isError && (
        <p role="alert">
          {t('traceUi.traceError')}{' '}
          <button className="btn" onClick={() => void result.refetch()}>
            {t('traceUi.retry')}
          </button>
        </p>
      )}
      {data && (
        <>
          <p className="mb-3">
            {t('traceUi.summary', { before: data.stats.before_count, after: data.stats.after_count })} · {data.terminal.outcome_ru}
          </p>
          <label>
            <input type="checkbox" checked={keyOnly} onChange={(e) => setKeyOnly(e.target.checked)} /> {t('traceUi.keyOnly')}
          </label>
          {(data.stats.truncated_after || data.stats.truncated_before) && <p role="status">{t('traceUi.truncated')}</p>}
          <div role="tablist" className="trace-tabs my-3">
            {['before', 'subject', 'after'].map((zone) => (
              <button key={zone} role="tab" aria-selected={tab === zone} className="btn" onClick={() => setTab(zone)}>
                {t(`traceUi.${zone}`)}
              </button>
            ))}
          </div>
          <div className="trace-columns mt-3" data-tab={tab}>
            <section className="trace-before" aria-label={t('traceUi.before')}>
              <h2>{t('traceUi.before')} →</h2>
              {data.before
                .filter((e) => !keyOnly || e.importance === 'key')
                .map((e) => (
                  <EventCard key={e.id} event={e} onSelect={select} />
                ))}
              <TraceGroups groups={beforeGroups} />
              {!data.before.length && <p>{t('traceUi.noBefore')}</p>}
            </section>
            <section className="trace-subject" aria-label={t('traceUi.subject')}>
              <h2>{t('traceUi.subject')}</h2>
              <SubjectCard trace={data} />
            </section>
            <section className="trace-after" aria-label={t('traceUi.after')}>
              <h2>→ {t('traceUi.after')}</h2>
              {data.after
                .filter((e) => !keyOnly || e.importance === 'key')
                .map((e) => (
                  <EventCard key={e.id} event={e} onSelect={select} />
                ))}
              <TraceGroups groups={data.groups.filter((g) => !beforeGroups.includes(g))} />
              {data.pending.map((p, i) => (
                <div key={i} className="my-2 rounded-xl border-2 border-dashed border-line p-3">
                  ◷ {p.kind_ru} · {p.due_sim && new Date(p.due_sim).toLocaleString()}
                </div>
              ))}
              <article className="sticky bottom-0 mt-3 rounded-xl border-2 border-brand bg-surface p-4">
                <h3>⚑ {t('traceUi.terminal')}</h3>
                <p>{data.terminal.outcome_ru}</p>
                <small>{t(data.terminal.reached ? 'traceUi.reached' : 'traceUi.waiting')}</small>
              </article>
            </section>
          </div>
        </>
      )}
      {details && (
        <aside
          role="dialog"
          aria-label={t('traceUi.event')}
          className="fixed inset-y-12 right-0 z-40 w-[min(420px,100vw)] overflow-auto border-l border-line bg-surface p-5 shadow-xl"
        >
          <button className="btn float-right" onClick={() => setDetails(null)} aria-label={t('traceUi.close')}>
            ×
          </button>
          <h2>{details.title_ru}</h2>
          <p className="my-3">{details.brief_ru}</p>
          <dl>
            {details.key_facts.map((f, i) => (
              <div key={i} className="my-2">
                <dt className="text-xs text-muted">{f.label_ru}</dt>
                <dd>{f.value_ru}</dd>
              </div>
            ))}
          </dl>
          {details.badges.llm_source && <p>{details.badges.llm_source}</p>}
          {details.links.engine_step && (
            <Link className="btn" to={details.links.engine_step}>
              {t('traceUi.engine')}
            </Link>
          )}
          {details.links.trace && (
            <Link className="btn" to={details.links.trace} onClick={() => setDetails(null)}>
              {t('traceUi.center')}
            </Link>
          )}
        </aside>
      )}
    </main>
  )
}

function TraceGroups({ groups }: { groups: Trace['groups'] }) {
  const { t } = useTranslation()
  return (
    <>
      {groups.map((g, i) => (
        <details key={i} className="my-2 rounded border border-line p-3">
          <summary>
            +{g.count} · {t(`traceUi.eventKind.${g.kind}`, { defaultValue: g.kind })}
          </summary>
          <p>{g.expand_hint_ru}</p>
          {g.sample_refs.map((r) => (
            <div key={r}>
              <IdLink kind={g.kind === 'signal_created' ? 'signal' : 'notification'} value={r} />
            </div>
          ))}
        </details>
      ))}
    </>
  )
}
