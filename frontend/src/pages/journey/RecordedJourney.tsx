import { useEffect, useMemo, useReducer, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { getJourney } from '@/shared/api/trace'
import { EventCard } from '@/pages/trace/components/EventCard'
import { ErrorBox } from '@/shared/ui'
import { frameDelay, initialPlayback, playbackReducer, presenterNotes, timeline, visibleJourney } from './playback'

export function RecordedJourney({ reference, mode }: { reference: string; mode: 'replay' | 'presenter' }) {
  const { t, i18n } = useTranslation()
  const result = useQuery({
    queryKey: ['journey-recording', reference, mode],
    queryFn: () => getJourney(reference, 'any', mode === 'presenter'),
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    retry: 1,
  })
  const [state, dispatch] = useReducer(playbackReducer, initialPlayback)
  const [stageIndex, setStageIndex] = useState(0)
  const [help, setHelp] = useState(false)
  const [timer, setTimer] = useState({ elapsed: 0, started: null as number | null })
  const [now, setNow] = useState(Date.now())
  const frames = useMemo(() => (result.data ? timeline(result.data) : []), [result.data])
  const view = result.data && (mode === 'replay' ? visibleJourney(result.data, frames, state.cursor) : result.data)
  const stage =
    mode === 'presenter'
      ? view?.stages[stageIndex]
      : (view?.stages.find((s) => s.status === 'active') ??
        view?.stages.find((s) => s.stage === [...frames.slice(0, state.cursor + 1)].reverse().find((f) => f.stage)?.stage))
  const step = (delta: number) => {
    if (mode === 'presenter') setStageIndex((i) => Math.max(0, Math.min((view?.stages.length ?? 1) - 1, i + delta)))
    else {
      dispatch({ type: 'pause' })
      dispatch({ type: 'step', delta, length: frames.length })
    }
  }
  useEffect(() => {
    if (!state.playing || !frames.length) return
    // Браузер ограничивает setTimeout 32-битным интервалом; долгие паузы делятся на части.
    let remaining = frameDelay(frames, state.cursor, state.tempo)
    let timeout: ReturnType<typeof setTimeout>
    const schedule = () => {
      const part = Math.min(remaining, 2_000_000_000)
      timeout = setTimeout(() => {
        remaining -= part
        if (remaining > 0) schedule()
        else dispatch({ type: 'step', delta: 1, length: frames.length })
      }, part)
    }
    schedule()
    return () => clearTimeout(timeout)
  }, [frames, state.cursor, state.playing, state.tempo])
  useEffect(() => {
    if (timer.started === null) return
    const interval = setInterval(() => setNow(Date.now()), 250)
    return () => clearInterval(interval)
  }, [timer.started])
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (
        e.altKey ||
        e.ctrlKey ||
        e.metaKey ||
        (e.target instanceof Element && e.target.closest('input,textarea,select,[contenteditable="true"],[role="dialog"]'))
      )
        return
      if (e.key === '?') {
        e.preventDefault()
        setHelp((v) => !v)
      }
      if (e.key === 'Escape') setHelp(false)
      if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
        e.preventDefault()
        step(e.key === 'ArrowLeft' ? -1 : 1)
      }
      if (e.code === 'Space' && mode === 'replay' && !(e.target instanceof Element && e.target.closest('button,a'))) {
        e.preventDefault()
        dispatch({ type: state.playing ? 'pause' : 'play' })
      }
    }
    window.addEventListener('keydown', key)
    return () => window.removeEventListener('keydown', key)
  })
  const timerMs = timer.elapsed + (timer.started === null ? 0 : Math.max(0, now - timer.started))
  const frame = frames[state.cursor]
  const notes = stage ? presenterNotes(stage.events) : []
  return (
    <section className="space-y-4 p-4 lg:p-5" aria-label={t(`journeyModes.${mode}`)}>
      <header className="card flex flex-wrap items-center gap-3 p-4">
        <h1 className="text-xl font-semibold">
          {t(`journeyModes.${mode}`)} · {reference}
        </h1>
        <span className="rounded border border-line px-2 py-1 text-xs">{t('journeyModes.recorded')}</span>
        <button className="btn btn-sm ml-auto" onClick={() => setHelp((v) => !v)} aria-expanded={help}>
          {t('journeyModes.help')}
        </button>
        <p className="w-full text-sm text-muted">{t('journeyModes.readOnly')}</p>
      </header>
      {help && (
        <aside className="card p-4" role="note">
          {t('journeyModes.shortcuts')}
        </aside>
      )}
      {result.isPending && <p role="status">{t('traceUi.loading')}</p>}
      {result.isError && <ErrorBox error={result.error} />}
      {view && (
        <>
          <div className="card flex flex-wrap items-center gap-2 p-3" aria-label={t('journeyModes.controls')}>
            <button className="btn btn-sm" onClick={() => step(-1)} disabled={mode === 'presenter' ? stageIndex === 0 : state.cursor < 0}>
              {t('journeyModes.previous')}
            </button>
            {mode === 'replay' && (
              <>
                <button
                  className="btn btn-primary btn-sm"
                  disabled={!frames.length || state.cursor >= frames.length - 1}
                  onClick={() => dispatch({ type: state.playing ? 'pause' : 'play' })}
                >
                  {t(state.playing ? 'journeyModes.pause' : 'journeyModes.play')}
                </button>
                <button className="btn btn-sm" onClick={() => dispatch({ type: 'reset' })}>
                  {t('journeyModes.reset')}
                </button>
                <label className="text-sm">
                  {t('journeyModes.tempo')}{' '}
                  <select className="input" value={state.tempo} onChange={(e) => dispatch({ type: 'tempo', value: e.target.value as typeof state.tempo })}>
                    <option value="compressed">{t('journeyModes.compressed')}</option>
                    <option value="real">{t('journeyModes.real')}</option>
                  </select>
                </label>
                <output className="text-sm num" aria-live="polite">
                  {state.cursor + 1} / {frames.length}
                </output>
              </>
            )}
            <button
              className="btn btn-sm"
              onClick={() => step(1)}
              disabled={mode === 'presenter' ? stageIndex >= view.stages.length - 1 : state.cursor >= frames.length - 1}
            >
              {t('journeyModes.next')}
            </button>
            {mode === 'presenter' && (
              <>
                <output role="timer" className="ml-auto font-mono text-xl">
                  {String(Math.floor(timerMs / 60000)).padStart(2, '0')}:{String(Math.floor(timerMs / 1000) % 60).padStart(2, '0')}
                </output>
                <button
                  className="btn btn-sm"
                  onClick={() => {
                    const at = Date.now()
                    setNow(at)
                    setTimer((v) => (v.started === null ? { ...v, started: at } : { elapsed: v.elapsed + at - v.started, started: null }))
                  }}
                >
                  {t(timer.started === null ? 'journeyModes.timerStart' : 'journeyModes.timerPause')}
                </button>
                <button className="btn btn-sm" onClick={() => setTimer({ elapsed: 0, started: null })}>
                  {t('journeyModes.timerReset')}
                </button>
              </>
            )}
          </div>
          {mode === 'replay' && state.cursor === frames.length - 1 && frames.length > 0 && (
            <p role="status">
              {t('journeyModes.finished')} · {view.summary.outcome_ru}
            </p>
          )}
          {!frames.length && <p role="status">{t('journeyModes.noEvents')}</p>}
          <ol className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
            {view.stages.map((s, i) => (
              <li key={s.stage}>
                <button
                  className={`w-full rounded-xl border p-3 text-left ${stage?.stage === s.stage ? 'border-brand bg-brand-soft' : s.status === 'pending' ? 'border-dashed border-line' : 'border-line'}`}
                  disabled={mode === 'replay'}
                  aria-current={stage?.stage === s.stage ? 'step' : undefined}
                  onClick={() => setStageIndex(i)}
                >
                  <strong>
                    {i + 1}. {t(`journeyUi.stage.${s.stage}`)}
                  </strong>
                  <span className="mt-1 block text-xs text-muted">
                    {t(`journeyUi.status.${s.status}`)} · {t('journeyUi.events', { n: s.events.length })}
                  </span>
                </button>
              </li>
            ))}
          </ol>
          <div className={`grid gap-4 ${mode === 'replay' ? 'lg:grid-cols-2' : ''}`}>
            <section className={`card p-5 ${mode === 'presenter' ? 'mx-auto w-full max-w-5xl text-xl lg:p-8' : ''}`} aria-label={t('journeyUi.bank')}>
              <h2 className={mode === 'presenter' ? 'mb-6 text-3xl font-semibold' : 'mb-3 font-semibold'}>
                {stage ? t(`journeyUi.stage.${stage.stage}`) : t('journeyModes.beforeStart')}
              </h2>
              {mode === 'presenter' ? (
                <>
                  <aside className="mb-6 rounded-xl bg-brand-soft p-5" aria-label={t('journeyModes.notes')}>
                    <h3 className="mb-2 font-semibold">{t('journeyModes.notes')}</h3>
                    {notes.length ? notes.map((note) => <p key={note}>{note}</p>) : <p>{t('journeyModes.noNotes')}</p>}
                  </aside>
                  {!stage?.events.length && <p>{t('journeyLive.pendingStage')}</p>}
                  {stage?.events.map((e) => (
                    <article key={e.id} className="mb-4 border-b border-line pb-4">
                      <h3 className="font-semibold">{e.title_ru}</h3>
                      <p className="mt-2">{e.brief_ru}</p>
                    </article>
                  ))}
                </>
              ) : (
                frame?.event && (
                  <>
                    <EventCard event={frame.event} />
                    <p className="my-3 text-xs text-muted">{new Date(frame.at).toLocaleString(i18n.language)}</p>
                    {frame.event.links.trace && (
                      <Link className="text-brand text-sm" to={frame.event.links.trace}>
                        {t('traceUi.title')}
                      </Link>
                    )}
                  </>
                )
              )}
            </section>
            {(mode === 'replay' || stage?.stage === 'client_outcome') && (
              <section className="card p-5" aria-label={t('journeyUi.client')}>
                <h2 className="mb-3 font-semibold">{t('journeyUi.client')}</h2>
                {!view.client_lane.length && <p className="text-muted">{t('journeyModes.noMessages')}</p>}
                {view.client_lane.map((m, i) => (
                  <article key={i} className="mb-3 rounded-xl border border-line p-3">
                    <p>{m.text_ru}</p>
                    <p className="mt-2 text-xs text-muted">{new Date(m.delivered_at).toLocaleString(i18n.language)}</p>
                  </article>
                ))}
              </section>
            )}
          </div>
        </>
      )}
    </section>
  )
}
