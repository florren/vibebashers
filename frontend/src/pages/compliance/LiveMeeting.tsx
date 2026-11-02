import { IdLink } from '@/shared/components/IdLink'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { clsx } from 'clsx'
import { Mic, Square, User, UserRound } from 'lucide-react'
import { useComplianceBranches, useRefs, useStartMicSession, useSttProviders } from '@/shared/api/hooks'
import type { MicSession, SttMessage } from '@/shared/api/client'
import { micSupported, startMic, type MicHandle } from '@/shared/audio/mic'
import { startWebSpeech, webSpeechSupported } from '@/shared/audio/webSpeech'
import { tEnum } from '@/shared/i18n'
import { Badge, ErrorBox, Section } from '@/shared/ui'

type Mode = 'manual' | 'auto' | 'stereo'
type Speaker = 'employee' | 'client'
type Utt = NonNullable<SttMessage['utterance']> & { trigger?: SttMessage['trigger'] }

const wsUrl = (path: string) => `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}${path}`

/** Живая встреча (B10): микрофон → /ws/audio → реплики → детектор мисселлинга → алерты и отчёт. */
export function LiveMeeting({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation()
  const branches = useComplianceBranches()
  const providers = useSttProviders()
  const products = useRefs('products')
  const start = useStartMicSession()
  const [branchId, setBranchId] = useState<number | null>(null)
  const [employeeId, setEmployeeId] = useState<number | null>(null)
  const [product, setProduct] = useState('')
  const [provider, setProvider] = useState('')
  const [mode, setMode] = useState<Mode>('manual')
  const [session, setSession] = useState<MicSession | null>(null)
  const [status, setStatus] = useState<'idle' | 'connecting' | 'live' | 'closing' | 'closed'>('idle')
  const [partial, setPartial] = useState<Record<number, string>>({})
  const [utts, setUtts] = useState<Utt[]>([])
  const [speaker, setSpeaker] = useState<Speaker>('employee')
  const [sess, setSess] = useState<{ trigger_count: number; status: string; alert_threshold: number } | null>(null)
  const [report, setReport] = useState<SttMessage['report'] | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [level, setLevel] = useState(0)
  const [model, setModel] = useState<string | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const micRef = useRef<MicHandle | null>(null)
  const speechRef = useRef<{ stop: () => void } | null>(null)
  const listRef = useRef<HTMLOListElement>(null)

  const avail = useMemo(() => (providers.data ?? []).filter((p) => p.available), [providers.data])
  useEffect(() => {
    if (!provider && avail.length) setProvider((avail.find((p) => p.is_default) ?? avail[0])!.code!)
  }, [avail, provider])
  useEffect(() => {
    const b = branches.data?.[0]
    if (branchId == null && b?.id) {
      setBranchId(b.id)
      setEmployeeId(b.employees?.find((e) => e.is_active)?.id ?? null)
    }
  }, [branches.data, branchId])
  const branch = branches.data?.find((b) => b.id === branchId)
  const prov = avail.find((p) => p.code === provider)
  const isBrowser = provider === 'browser'

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight })
  }, [utts, partial])

  const stopAll = useCallback(() => {
    micRef.current?.stop()
    micRef.current = null
    speechRef.current?.stop()
    speechRef.current = null
  }, [])

  const sendSpeaker = (sp: Speaker) => {
    setSpeaker(sp)
    if (wsRef.current?.readyState === WebSocket.OPEN) wsRef.current.send(JSON.stringify({ type: 'speaker', speaker: sp }))
  }

  useEffect(() => {
    if (status !== 'live' || mode !== 'manual') return
    const onKey = (e: KeyboardEvent) => {
      if (e.code === 'Space' && !(e.target instanceof HTMLInputElement) && !(e.target instanceof HTMLTextAreaElement)) {
        e.preventDefault()
        sendSpeaker(speaker === 'employee' ? 'client' : 'employee')
      }
    }
    addEventListener('keydown', onKey)
    return () => removeEventListener('keydown', onKey)
  }, [status, mode, speaker])

  const begin = async () => {
    if (!employeeId || !provider) return
    setErr(null)
    setUtts([])
    setPartial({})
    setReport(null)
    setSess(null)
    setStatus('connecting')
    try {
      const s = await start.mutateAsync({ employee_id: employeeId, deal_product: product || null, stt_provider: provider, diarization_mode: mode })
      setSession(s)
      const ws = new WebSocket(wsUrl(s.audio_ws_url))
      ws.binaryType = 'arraybuffer'
      wsRef.current = ws
      ws.onopen = async () => {
        ws.send(JSON.stringify({ type: 'hello', provider, sample_rate: s.sample_rate, channels: s.channels, speaker }))
        try {
          if (isBrowser) {
            speechRef.current = startWebSpeech({
              onResult: (text, isFinal) => ws.readyState === WebSocket.OPEN && ws.send(JSON.stringify({ type: 'text', text, is_final: isFinal })),
              onError: (e) => e !== 'no-speech' && setErr(t('live.speechError', { e })),
            })
          } else {
            micRef.current = await startMic({ channels: s.channels, onFrame: (pcm) => ws.readyState === WebSocket.OPEN && ws.send(pcm) })
          }
          setStatus('live')
        } catch (e) {
          setErr(String(e instanceof Error ? e.message : e))
          ws.send(JSON.stringify({ type: 'end' }))
        }
      }
      ws.onmessage = (ev: MessageEvent<string>) => {
        const m = JSON.parse(ev.data) as SttMessage
        if (m.type === 'ready') setModel(m.model ?? null)
        else if (m.type === 'partial') setPartial((p) => ({ ...p, [m.channel ?? 1]: m.text ?? '' }))
        else if (m.type === 'final' && m.utterance) {
          setPartial((p) => ({ ...p, [m.channel ?? 1]: '' }))
          setUtts((u) => [...u, { ...m.utterance!, trigger: m.trigger ?? null }])
          if (m.session) setSess(m.session)
        } else if (m.type === 'error') setErr(m.error ?? 'error')
        else if (m.type === 'closed') {
          setReport(m.report ?? null)
          setStatus('closed')
        }
      }
      ws.onclose = () => {
        stopAll()
        setStatus((st) => (st === 'closed' ? st : 'closed'))
      }
      ws.onerror = () => setErr(t('live.wsError'))
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e))
      setStatus('idle')
    }
  }

  const finish = () => {
    setStatus('closing')
    stopAll()
    if (wsRef.current?.readyState === WebSocket.OPEN) wsRef.current.send(JSON.stringify({ type: 'end' }))
  }

  useEffect(() => {
    const id = setInterval(() => setLevel(micRef.current?.level() ?? 0), 120)
    return () => clearInterval(id)
  }, [])
  useEffect(() => () => {
    stopAll()
    wsRef.current?.close()
  }, [stopAll])

  const live = status === 'live' || status === 'connecting' || status === 'closing'
  const supported = isBrowser ? webSpeechSupported() : micSupported()

  return (
    <div className="mx-auto max-w-4xl space-y-3">
      <Section
        title={t('live.title')}
        right={
          <div className="flex items-center gap-2">
            {prov?.external_service && <Badge tone="warn">{t('live.external')}</Badge>}
            {model && <Badge tone="neutral">{model}</Badge>}
            {session && <IdLink kind="audio_session" value={session.public_id} />}
            <button className="btn btn-ghost btn-sm" onClick={onClose} disabled={live}>
              {t('common.close')}
            </button>
          </div>
        }
      >
        <div className="grid gap-3 p-3 md:grid-cols-5">
          <label className="block text-xs">
            <div className="mb-1 text-muted">{t('live.branch')}</div>
            <select
              className="input w-full"
              disabled={live}
              value={branchId ?? ''}
              onChange={(e) => {
                const id = Number(e.target.value)
                setBranchId(id)
                setEmployeeId(branches.data?.find((b) => b.id === id)?.employees?.find((x) => x.is_active)?.id ?? null)
              }}
            >
              {(branches.data ?? []).map((b) => (
                <option key={b.id} value={b.id}>
                  {b.code} · {b.city_name}
                </option>
              ))}
            </select>
          </label>
          <label className="block text-xs">
            <div className="mb-1 text-muted">{t('live.employee')}</div>
            <select className="input w-full" disabled={live} value={employeeId ?? ''} onChange={(e) => setEmployeeId(Number(e.target.value))}>
              {(branch?.employees ?? []).map((e) => (
                <option key={e.id} value={e.id}>
                  {e.display_name} · {e.position}
                </option>
              ))}
            </select>
          </label>
          <label className="block text-xs">
            <div className="mb-1 text-muted">{t('live.product')}</div>
            <select className="input w-full" disabled={live} value={product} onChange={(e) => setProduct(e.target.value)}>
              <option value="">—</option>
              {(products.data ?? []).map((p) => (
                <option key={String(p.code)} value={String(p.code)}>
                  {String(p.name_ru)}
                </option>
              ))}
            </select>
          </label>
          <label className="block text-xs">
            <div className="mb-1 text-muted">{t('live.provider')}</div>
            <select className="input w-full" disabled={live} value={provider} onChange={(e) => setProvider(e.target.value)}>
              {avail.map((p) => (
                <option key={p.code} value={p.code}>
                  {p.label_ru}
                </option>
              ))}
            </select>
          </label>
          <label className="block text-xs">
            <div className="mb-1 text-muted">{t('live.mode')}</div>
            <select className="input w-full" disabled={live} value={mode} onChange={(e) => setMode(e.target.value as Mode)}>
              <option value="manual">{t('live.modes.manual')}</option>
              <option value="auto">{t('live.modes.auto')}</option>
              {!isBrowser && <option value="stereo">{t('live.modes.stereo')}</option>}
            </select>
          </label>
        </div>
        <div className="flex flex-wrap items-center gap-2 border-t border-line px-3 py-2">
          {!live ? (
            <button className="btn btn-primary" disabled={!employeeId || !provider || !supported || start.isPending} onClick={() => void begin()}>
              <Mic size={14} /> {t('live.start')}
            </button>
          ) : (
            <button className="btn btn-danger" onClick={finish} disabled={status === 'closing'}>
              <Square size={14} /> {status === 'closing' ? t('live.closing') : t('live.stop')}
            </button>
          )}
          {!supported && <span className="text-xs text-danger">{t(isBrowser ? 'live.noWebSpeech' : 'live.noMic')}</span>}
          {live && !isBrowser && (
            <div className="flex items-center gap-1" title={t('live.level')}>
              <div className="h-2 w-28 overflow-hidden rounded bg-raised">
                <div className="h-full bg-ok transition-[width]" style={{ width: `${Math.min(100, Math.round(level * 140))}%` }} />
              </div>
            </div>
          )}
          {live && mode === 'manual' && (
            <div className="ml-2 flex items-center gap-1 text-xs">
              <span className="text-muted">{t('live.speaking')}</span>
              <button className={clsx('chip', speaker === 'employee' && 'chip-on')} onClick={() => sendSpeaker('employee')}>
                <UserRound size={12} /> {t('live.employeeShort')}
              </button>
              <button className={clsx('chip', speaker === 'client' && 'chip-on')} onClick={() => sendSpeaker('client')}>
                <User size={12} /> {t('live.clientShort')}
              </button>
              <span className="text-faint">{t('live.spaceHint')}</span>
            </div>
          )}
          {sess && (
            <div className="ml-auto flex items-center gap-2 text-xs">
              <Badge tone={sess.status === 'alerted' ? 'danger' : sess.trigger_count > 0 ? 'warn' : 'ok'}>
                {t('live.triggers', { n: sess.trigger_count, max: sess.alert_threshold })}
              </Badge>
              <Badge tone="neutral">{tEnum('compliance.sessionStatus', sess.status)}</Badge>
            </div>
          )}
        </div>
        {err && (
          <div className="px-3 pb-2">
            <ErrorBox error={new Error(err)} compact />
          </div>
        )}
        {start.error && (
          <div className="px-3 pb-2">
            <ErrorBox error={start.error} compact />
          </div>
        )}
        <p className="px-3 pb-2 text-[11px] text-faint">{t(isBrowser ? 'live.hintBrowser' : 'live.hintServer')}</p>
      </Section>

      {(utts.length > 0 || live) && (
        <Section title={t('live.transcript')} right={<span className="text-xs text-muted">{t('live.uttCount', { n: utts.length })}</span>}>
          <ol ref={listRef} className="max-h-[46vh] space-y-1.5 overflow-y-auto p-3">
            {utts.map((u) => (
              <li key={u.utterance_id} className={clsx('flex gap-2', u.speaker === 'client' && 'flex-row-reverse')}>
                <div className={clsx('max-w-[80%] rounded-lg border px-3 py-1.5 text-sm', u.trigger ? 'border-danger/60 bg-danger/10' : 'border-line bg-raised')}>
                  <div className="mb-0.5 flex items-center gap-2 text-[11px] text-muted">
                    <span className="num">#{u.seq}</span>
                    <span className="font-medium">{t(u.speaker === 'client' ? 'live.clientShort' : 'live.employeeShort')}</span>
                    {u.speaker_source !== 'manual' && <span title={u.speaker_source}>{Math.round(u.speaker_confidence * 100)}%</span>}
                    <span>
                      {t('live.timeRange', { start: (u.t0_ms / 1000).toFixed(1), end: (u.t1_ms / 1000).toFixed(1) })}
                    </span>
                  </div>
                  <div>{u.text}</div>
                  {u.trigger && (
                    <div className="mt-1 rounded border border-danger/40 bg-surface px-2 py-1 text-xs">
                      <Badge tone="danger">{tEnum('compliance.pattern', u.trigger.pattern_code)}</Badge> <span className="text-muted">{u.trigger.confidence.toFixed(2)}</span>
                      <div className="mt-0.5">{u.trigger.explanation_ru}</div>
                      {u.trigger.recommendation_ru && <div className="text-muted">{u.trigger.recommendation_ru}</div>}
                    </div>
                  )}
                </div>
              </li>
            ))}
            {Object.entries(partial)
              .filter(([, v]) => v)
              .map(([ch, v]) => (
                <li key={`p${ch}`} className={clsx('flex gap-2', mode === 'stereo' && ch === '2' && 'flex-row-reverse')}>
                  <div className="max-w-[80%] rounded-lg border border-dashed border-line px-3 py-1.5 text-sm text-muted">{v}…</div>
                </li>
              ))}
            {live && utts.length === 0 && !Object.values(partial).some(Boolean) && <li className="text-sm text-muted">{t('live.listening')}</li>}
          </ol>
        </Section>
      )}

      {report && (
        <Section title={t('live.report')} right={<Badge tone={(report.findings ?? []).length ? 'warn' : 'ok'}>{t('compliance.findings')}: {(report.findings ?? []).length}</Badge>}>
          <div className="p-3 text-sm">
            {report.overall_ru && <p className="mb-2">{String(report.overall_ru)}</p>}
            <ul className="divide-y divide-line">
              {(report.findings ?? []).map((f, i) => (
                <li key={i} className="py-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone="danger">{tEnum('compliance.pattern', f.pattern_code)}</Badge>
                    <Badge tone="neutral">{tEnum('compliance.family', f.family)}</Badge>
                    <span className="text-[11px] text-muted">
                      {t('compliance.turn', { n: f.turn_seq })} · {f.confidence.toFixed(2)}
                    </span>
                  </div>
                  <blockquote className="mt-1 border-l-2 border-danger/60 pl-2 italic">«{f.quote}»</blockquote>
                  <p className="mt-1 text-muted">{f.explanation_ru}</p>
                </li>
              ))}
            </ul>
            <p className="mt-2 text-[11px] text-faint">{t('live.reportHint')}</p>
          </div>
        </Section>
      )}
    </div>
  )
}
