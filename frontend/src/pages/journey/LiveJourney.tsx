import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { getJourney } from '@/shared/api/trace'
import { ApiError } from '@/shared/api/client'
import { useClients } from '@/shared/api/hooks'
import { IdLink } from '@/shared/components/IdLink'
import { EventCard } from '@/pages/trace/components/EventCard'
import { ErrorBox } from '@/shared/ui'
import { useWs } from '@/shared/ws/client'
import { ROUTES } from '@/shared/routes'
import { AgentExecution } from './AgentExecution'
import { loadClient, loadEconomics, loadRun, loadSignal, numericRef, sendJourneyMessage } from './api'
import { elapsedSeconds, NODE_STAGE } from './timing'

type Origin = 'jury' | 'feed' | 'sim' | 'any'

export function LiveJourney({ onSubject }: { onSubject: (ref: string) => void }) {
  const { ref } = useParams()
  const { t, i18n } = useTranslation()
  const nav = useNavigate()
  const qc = useQueryClient()
  const requestKey = useRef<{ signature: string; id: string } | null>(null)
  const messageLog = useRef<HTMLDivElement | null>(null)
  const followTail = useRef(true)
  const [origin, setOrigin] = useState<Origin>('jury')
  const [text, setText] = useState('')
  const [clientId, setClientId] = useState('')
  const [clientSearch, setClientSearch] = useState('')
  const [channel, setChannel] = useState<'chat' | 'email' | 'social'>('chat')
  const [followup, setFollowup] = useState(false)
  const [selectedRunId, setSelectedRunId] = useState<number | null>(null)
  const [selectedStage, setSelectedStage] = useState<string | null>(null)
  const [now, setNow] = useState(Date.now())
  const wsStatus = useWs((s) => s.status)
  const events = useWs((s) => s.events)
  const clients = useClients({ q: clientSearch || undefined })
  const result = useQuery({
    queryKey: ['journey', ref, origin],
    queryFn: () => getJourney(ref, origin),
    refetchInterval: 2000,
    retry: (count, e) => !(e instanceof ApiError && e.status === 404) && count < 1,
  })
  const data = result.data
  useEffect(() => {
    if (data) onSubject(data.subject.ref)
  }, [data, onSubject])
  const traceEvents = data?.stages.flatMap((s) => s.events) ?? []
  const subjectSignal = data?.subject.kind === 'signal' ? data.subject.ref : traceEvents.find((e) => e.object_ref?.kind === 'signal')?.object_ref?.ref
  const signalId = numericRef(subjectSignal, 'SIG')
  const signal = useQuery({
    queryKey: ['signals', 'journey', signalId],
    queryFn: () => loadSignal(signalId!),
    enabled: signalId !== null,
    refetchInterval: 2000,
  })
  const relatedRunIds = [
    ...new Set([
      ...(signal.data?.agent_runs ?? []).flatMap((r) => (r.id == null ? [] : [r.id])),
      ...traceEvents.flatMap((e) => {
        const linkedRun = e.links.engine_step?.match(/^\/engine\/(\d+)(?:[/?#]|$)/)
        return linkedRun ? [Number(linkedRun[1])] : []
      }),
      ...traceEvents.flatMap((e) => (e.object_ref?.kind === 'agent_run' ? [numericRef(e.object_ref.ref, 'AR')] : [])).filter((id): id is number => id !== null),
    ]),
  ]
    .sort((a, b) => b - a)
    .slice(0, 10)
  const runQueries = useQueries({
    queries: relatedRunIds.map((id) => ({ queryKey: ['agent', 'journey', id], queryFn: () => loadRun(id), refetchInterval: 2000 })),
  })
  const availableRuns = runQueries.flatMap((q) => (q.data ? [q.data] : []))
  const preferredRun =
    availableRuns.find((r) => r.kind === 'agent' && (!r.outcome || r.outcome === 'awaiting_human')) ??
    availableRuns.find((r) => r.kind === 'agent') ??
    availableRuns[0]
  const runId = selectedRunId && relatedRunIds.includes(selectedRunId) ? selectedRunId : (preferredRun?.id ?? null)
  const run = runQueries.find((q) => q.data?.id === runId)
  const runData = run?.data
  const liveStep = events.find((e) => e.topic === 'agent' && (e.type === 'step_started' || e.type === 'step_finished') && e.data.run_id === runId)
  const current =
    runData?.outcome && runData.outcome !== 'awaiting_human'
      ? null
      : typeof liveStep?.data.node === 'string'
        ? liveStep.data.node
        : (runData?.current_node ?? null)
  const currentStage = current ? NODE_STAGE[current] : undefined
  const activeStage = currentStage ?? data?.stages.find((s) => s.status === 'active' || s.status === 'waiting_human')?.stage
  const stage = data?.stages.find((s) => s.stage === (selectedStage ?? activeStage)) ?? data?.stages.at(-1)
  const currentClientId = signal.data?.client?.id ?? null
  const client = useQuery({
    queryKey: ['clients', 'journey', currentClientId],
    queryFn: () => loadClient(currentClientId!),
    enabled: currentClientId !== null,
  })
  const incidentId = signal.data?.incidents?.at(-1)?.id ?? numericRef(data?.subject.kind === 'incident' ? data.subject.ref : undefined, 'INC')
  const economics = useQuery({
    queryKey: ['incidents', 'journey-economics', incidentId],
    queryFn: () => loadEconomics(incidentId!),
    enabled: incidentId !== null,
    refetchInterval: 5000,
  })
  const send = useMutation({
    mutationFn: sendJourneyMessage,
    onSuccess: (id) => {
      requestKey.current = null
      setText('')
      setFollowup(true)
      setSelectedStage(null)
      setSelectedRunId(null)
      nav(ROUTES.journeyObject(`SIG-${String(id).padStart(6, '0')}`))
      void qc.invalidateQueries({ queryKey: ['journey'] })
      void qc.invalidateQueries({ queryKey: ['signals'] })
    },
  })
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [])
  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!text.trim() || send.isPending) return
    const signature = JSON.stringify([channel, text.trim(), clientId, followup ? signalId : null])
    if (requestKey.current?.signature !== signature) requestKey.current = { signature, id: `journey-${crypto.randomUUID()}` }
    send.mutate({
      channel,
      external_id: requestKey.current.id,
      client: { client_id: followup ? (signal.data?.client?.id ?? null) : clientId ? Number(clientId) : null },
      text: text.trim(),
      timestamp: new Date().toISOString(),
      geo: { source: 'none' },
      origin: 'jury',
      meta: followup && signalId ? { parent_signal_id: signalId } : {},
    })
  }
  const money = (value: number | null | undefined) =>
    value == null ? '—' : new Intl.NumberFormat(i18n.language, { style: 'currency', currency: 'RUB', maximumFractionDigits: 2 }).format(value)
  const empty = result.error instanceof ApiError && result.error.status === 404
  const incoming = traceEvents.filter((e) => e.kind === 'signal_created').sort((a, b) => a.ts_real.localeCompare(b.ts_real))
  const messages = [
    ...incoming.map((e) => ({ id: e.id, text: e.brief_ru, at: e.ts_real, sim: e.ts_sim, actor: 'client' })),
    ...(data?.client_lane ?? [])
      .filter(
        (m) =>
          m.channel_code !== 'client_reaction' ||
          !incoming.some((e) => e.brief_ru === m.text_ru && Math.abs(Date.parse(e.ts_real) - Date.parse(m.delivered_at)) < 1000),
      )
      .map((m) => ({
        id: `${m.channel_code}:${m.delivered_at}:${m.text_ru}`,
        text: m.text_ru,
        at: m.delivered_at,
        sim: m.delivered_sim,
        actor: m.channel_code === 'client_reaction' ? 'client' : 'bank',
      })),
  ].sort((a, b) => a.at.localeCompare(b.at))
  useEffect(() => {
    followTail.current = true
  }, [subjectSignal])
  useEffect(() => {
    if (followTail.current && messageLog.current) messageLog.current.scrollTop = messageLog.current.scrollHeight
  }, [messages.length, subjectSignal])
  const received = incoming.find((e) => e.object_ref?.ref === data?.subject.ref)?.ts_real ?? incoming[0]?.ts_real
  const replied = data?.client_lane.find(
    (m) => m.channel_code !== 'client_reaction' && received && Date.parse(m.delivered_at) >= Date.parse(received),
  )?.delivered_at
  const firstReply = received && replied ? Math.round((Date.parse(replied) - Date.parse(received)) / 1000) : null
  const source = [...new Set(traceEvents.flatMap((e) => (e.badges.llm_source ? [e.badges.llm_source] : [])))].join(' + ')
  return (
    <main className="min-h-0 flex-1 overflow-auto p-4 lg:p-5">
      <header className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">{t('journeyUi.title')}</h1>
          <p className="mt-1 text-sm text-muted">{t('journeyLive.subtitle')}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span role="status" className="rounded-full border border-line px-3 py-1">
            {t(wsStatus === 'open' ? 'journeyLive.connected' : 'journeyLive.polling')}
          </span>
          {source && (
            <span className="rounded border border-line px-2 py-1">
              {t('journeyLive.sources')}: {source}
            </span>
          )}
          {data && <IdLink kind={data.subject.kind} value={data.subject.ref} />}
          <label>
            {t('journeyLive.follow')}{' '}
            <select
              className="input"
              value={origin}
              onChange={(e) => {
                setOrigin(e.target.value as Origin)
                setSelectedStage(null)
                nav(ROUTES.journey)
              }}
            >
              {(['jury', 'feed', 'sim', 'any'] as const).map((o) => (
                <option key={o} value={o}>
                  {t(`journeyLive.origin.${o}`)}
                </option>
              ))}
            </select>
          </label>
        </div>
      </header>
      <section aria-label={t('journeyLive.economics')} className="mb-4 grid gap-3 md:grid-cols-2 lg:grid-cols-4">
        <div className="card p-4">
          <h2 className="text-xs text-muted">{t('journeyLive.clientValue')}</h2>
          <strong className="mt-2 block text-2xl num">{money(client.data?.clv_estimate_rub)}</strong>
          <p className="mt-1 text-xs text-muted">{client.data?.display_name ?? t('journeyLive.unidentified')}</p>
          {client.isError && <ErrorBox error={client.error} compact />}
        </div>
        <div className="card p-4">
          <h2 className="text-xs text-muted">{t('journeyLive.incidentRisk')}</h2>
          <strong className="mt-2 block text-2xl num">{money(economics.data?.potential_loss_rub)}</strong>
          <p className="mt-1 text-xs text-muted">{economics.data?.formula_ru ?? t('journeyLive.noIncident')}</p>
          {economics.isError && <ErrorBox error={economics.error} compact />}
        </div>
        <div className="card p-4">
          <h2 className="text-xs text-muted">{t('journeyLive.prevented')}</h2>
          <strong className="mt-2 block text-2xl num">{money(economics.data?.prevented_loss_rub)}</strong>
          <p className="mt-1 text-xs text-muted">{data?.summary.outcome_ru ?? t('journeyLive.startHint')}</p>
        </div>
        <div className="card p-4">
          <h2 className="text-xs text-muted">{t('journeyUi.firstReply')}</h2>
          <strong className="mt-2 block text-2xl num">{firstReply === null ? '—' : `${firstReply} ${t('journeyUi.sec')}`}</strong>
          <p className="mt-1 text-xs text-muted">{t('journeyLive.replyTiming')}</p>
        </div>
      </section>
      <div className="grid items-start gap-4 xl:grid-cols-[minmax(300px,0.85fr)_minmax(0,1.65fr)]">
        <section
          aria-label={t('journeyLive.conversation')}
          className="card flex flex-col overflow-hidden xl:sticky xl:top-0 xl:h-[calc(100dvh-360px)] xl:min-h-[340px]"
        >
          <div className="shrink-0 border-b border-line p-3">
            <h2 className="font-semibold">{t('journeyUi.client')}</h2>
            <p className="mt-1 text-xs text-muted">{t('journeyLive.deliveredOnly')}</p>
          </div>
          <div
            ref={messageLog}
            onScroll={(e) => {
              const el = e.currentTarget
              followTail.current = el.scrollHeight - el.scrollTop - el.clientHeight < 32
            }}
            className="max-h-[300px] min-h-24 flex-1 space-y-3 overflow-auto p-3 xl:min-h-0"
            role="log"
            aria-live="polite"
            aria-relevant="additions"
          >
            {messages.map((m) => (
              <article
                key={m.id}
                className={`max-w-[95%] rounded-xl border border-line p-3 ${m.actor === 'client' ? 'ml-auto bg-brand-soft' : 'mr-auto bg-raised'}`}
              >
                <p className="mb-1 text-xs font-medium text-muted">{t(`journeyLive.actor.${m.actor}`)}</p>
                <p className="whitespace-pre-wrap text-sm">{m.text}</p>
                <p className="mt-2 text-[11px] text-muted">
                  {t('traceUi.realTime')}: {new Date(m.at).toLocaleTimeString(i18n.language)}
                  {m.sim && ` · ${t('journeyLive.sim')}: ${new Date(m.sim).toLocaleTimeString(i18n.language)}`}
                </p>
              </article>
            ))}
            {!messages.length && <p className="text-sm text-muted">{t('journeyLive.startHint')}</p>}
            {!!messages.length && !data?.client_lane.length && (
              <p className="text-sm text-muted" role="status">
                {t(runData?.outcome === 'awaiting_human' ? 'journeyLive.waitingHumanReply' : 'journeyLive.waitingReply')}
              </p>
            )}
          </div>
          <form onSubmit={submit} className="max-h-[80%] shrink-0 space-y-2 overflow-y-auto border-t border-line p-3">
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                aria-pressed={!followup}
                className={`btn btn-sm ${!followup ? 'border-brand text-brand' : ''}`}
                onClick={() => {
                  setFollowup(false)
                  setText('')
                  send.reset()
                }}
              >
                {t('journeyLive.newRequest')}
              </button>
              {signalId !== null && (
                <button
                  type="button"
                  aria-pressed={followup}
                  className={`btn btn-sm ${followup ? 'border-brand text-brand' : ''}`}
                  onClick={() => setFollowup(true)}
                >
                  {t(followup ? 'journeyLive.followup' : 'journeyLive.resumeConversation')}
                </button>
              )}
            </div>
            <details className="text-xs">
              <summary className="cursor-pointer text-muted">
                {t('journeyLive.messageOptions')} · {t(`channel.${channel}`)}
              </summary>
              {!followup && (
                <div className="space-y-2 py-2">
                  <label className="block">
                    {t('journeyLive.findClient')}
                    <input className="input mt-1 w-full" value={clientSearch} onChange={(e) => setClientSearch(e.target.value)} />
                  </label>
                  <label className="block">
                    {t('jury.client')}
                    <select className="input mt-1 w-full" value={clientId} onChange={(e) => setClientId(e.target.value)}>
                      <option value="">{t('common.anonymous')}</option>
                      {clients.data?.map((c) => (
                        <option key={c.id} value={c.id}>
                          {c.display_name} · {c.public_id} · {c.segment_code}
                        </option>
                      ))}
                    </select>
                  </label>
                  {clients.isError && <ErrorBox error={clients.error} compact />}
                </div>
              )}
              <label className="block py-2">
                {t('jury.channel')}
                <select className="input ml-2" value={channel} onChange={(e) => setChannel(e.target.value as typeof channel)}>
                  {['chat', 'email', 'social'].map((c) => (
                    <option key={c} value={c}>
                      {t(`channel.${c}`)}
                    </option>
                  ))}
                </select>
              </label>
            </details>
            <label className="block text-xs">
              {t('journeyLive.message')}
              <textarea
                className="input mt-1 h-16 w-full resize-y py-2"
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder={t('jury.placeholder')}
                maxLength={4000}
                required
                minLength={3}
              />
            </label>
            {send.isError && <ErrorBox error={send.error} compact />}
            <button type="submit" className="btn btn-primary w-full" disabled={send.isPending || text.trim().length < 3}>
              {t(send.isPending ? 'journeyLive.sending' : 'journeyLive.send')}
            </button>
          </form>
        </section>
        <div className="min-w-0 space-y-4">
          {result.isError && !empty && <ErrorBox error={result.error} />}
          {signal.isError && <ErrorBox error={signal.error} />}
          {run?.isError && <ErrorBox error={run?.error} />}
          {availableRuns.length > 1 && (
            <label className="block text-xs">
              {t('journeyLive.selectRun')}{' '}
              <select className="input" value={selectedRunId ?? ''} onChange={(e) => setSelectedRunId(e.target.value ? Number(e.target.value) : null)}>
                <option value="">{t('journeyLive.autoRun')}</option>
                {availableRuns.map((r) => (
                  <option key={r.id} value={r.id}>
                    #{r.id} · {t(r.kind === 'client_twin' ? 'journeyLive.twin' : 'journeyLive.mainAgent')} ·{' '}
                    {r.outcome ? t(`engine.outcome.${r.outcome}`) : t('engine.outcome.running')}
                  </option>
                ))}
              </select>
            </label>
          )}
          <AgentExecution run={runData} current={current} onOpenSignal={(id) => nav(ROUTES.journeyObject(`SIG-${String(id).padStart(6, '0')}`))} />
          <section className="card p-4" aria-label={t('journeyUi.bank')}>
            <h2 className="mb-3 font-semibold">{t('journeyUi.bank')}</h2>
            {result.isPending && <p role="status">{t('traceUi.loading')}</p>}
            {empty && <p className="text-sm text-muted">{t('journeyLive.startHint')}</p>}
            <ol className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
              {data?.stages.map((s, i) => {
                const status =
                  s.stage === currentStage && runData?.outcome !== 'awaiting_human'
                    ? 'active'
                    : currentStage && s.status === 'active' && s.stage !== currentStage
                      ? 'done'
                      : s.status
                return (
                  <li key={s.stage}>
                    <button
                      type="button"
                      aria-pressed={stage?.stage === s.stage}
                      onClick={() => setSelectedStage(s.stage)}
                      className={`h-full w-full rounded-xl border p-3 text-left text-xs ${stage?.stage === s.stage ? 'border-brand bg-brand-soft' : status === 'pending' ? 'border-dashed border-line' : 'border-line'}`}
                    >
                      <strong className="block">
                        {i + 1}. {t(`journeyUi.stage.${s.stage}`)}
                      </strong>
                      <span className="mt-2 block">
                        {t(`journeyUi.status.${status}`)} · {t('journeyUi.events', { n: s.events.length })}
                      </span>
                    </button>
                  </li>
                )
              })}
            </ol>
            {selectedStage && (
              <button className="btn btn-sm my-2" onClick={() => setSelectedStage(null)}>
                {t('journeyLive.followActive')}
              </button>
            )}
            {stage && (
              <div className="mt-4 border-t border-line pt-3">
                <h3 className="font-medium">{t(`journeyUi.stage.${stage.stage}`)}</h3>
                <p className="text-xs text-muted">
                  {t('traceUi.realTime')}: {elapsedSeconds(stage.events, 'ts_real') ?? '—'} {t('journeyUi.sec')} · {t('journeyLive.sim')}:{' '}
                  {elapsedSeconds(stage.events, 'ts_sim') ?? '—'} {t('journeyUi.sec')}
                </p>
                {stage.status === 'waiting_human' && stage.events.find((e) => e.kind === 'human_request') && (
                  <p role="timer" className="my-3 rounded-xl border border-dashed border-warn p-3">
                    {t('journeyUi.waiting', {
                      n: Math.max(0, Math.floor((now - Date.parse(stage.events.find((e) => e.kind === 'human_request')!.ts_real)) / 1000)),
                    })}
                  </p>
                )}
                {!stage.events.length && <p className="mt-3 text-sm text-muted">{t('journeyLive.pendingStage')}</p>}
                {stage.events.map((e) => (
                  <div key={e.id}>
                    <EventCard event={e} />
                    <dl className="text-xs text-muted">
                      {e.key_facts.map((f, j) => (
                        <div key={j}>
                          {f.label_ru}: {f.value_ru}
                        </div>
                      ))}
                    </dl>
                    <div className="my-2 flex gap-3 text-xs">
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
              </div>
            )}
          </section>
        </div>
      </div>
    </main>
  )
}
