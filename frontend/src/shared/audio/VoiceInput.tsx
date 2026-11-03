import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { clsx } from 'clsx'
import { Mic, Square } from 'lucide-react'
import { useSttProviders } from '@/shared/api/hooks'
import { micSupported, microphoneOriginAllowed, startMic, type MicHandle } from './mic'
import { startWebSpeech, webSpeechSupported } from './webSpeech'
import type { Schemas } from '@/shared/api/client'
import { selectedDefaultProvider } from './providerSelection'

/** «Надиктовать» (T-206): используем только явно выбранный default из API; browser требует явного включения. */
export function VoiceInput({ onText, onInterim, onVoice, className, serverOnly = false, maxSeconds = 120 }: { onText: (text: string) => void; onInterim?: (text: string) => void; onVoice?: (meta: Schemas['VoiceMeta']) => void; className?: string; serverOnly?: boolean; maxSeconds?: number }) {
  const { t } = useTranslation()
  const prov = useSttProviders()
  const [rec, setRec] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const micRef = useRef<MicHandle | null>(null)
  const chunks = useRef<ArrayBuffer[]>([])
  const stopRef = useRef<(() => Promise<void>) | null>(null)
  useEffect(() => {
    if (!rec) return
    const timer = window.setTimeout(() => { void stopRef.current?.() }, maxSeconds * 1000)
    return () => window.clearTimeout(timer)
  }, [rec, maxSeconds])
  const speechRef = useRef<ReturnType<typeof startWebSpeech> | null>(null)
  const activeProvider = useRef<string | null>(null)
  const selected = prov.isError ? null : selectedDefaultProvider(prov.data ?? [])
  const secure = microphoneOriginAllowed(window.location, window.isSecureContext === true)
  const mode: 'server' | 'browser' | null = !selected ? null : selected.code === 'browser'
    ? !serverOnly && webSpeechSupported() ? 'browser' : null
    : micSupported() ? 'server' : null

  useEffect(() => () => {
    micRef.current?.stop()
    speechRef.current?.abort()
  }, [])
  useEffect(() => {
    if (!rec || secure && mode && activeProvider.current === selected?.code) return
    micRef.current?.stop(); micRef.current = null
    speechRef.current?.abort(); speechRef.current = null
    chunks.current = []
    setRec(false)
  }, [rec, secure, mode, selected?.code])
  if (!secure) {
    return <span className="text-xs text-muted">{t('voice.secureRequired')}</span>
  }
  if (prov.isError) return <span role="status" className="text-xs text-muted">{t('voice.providersUnavailable')}</span>
  if (!mode) return null

  const start = async () => {
    if (!selected || !mode) return
    activeProvider.current = selected.code ?? null
    setErr(null)
    try {
      if (mode === 'server') {
        chunks.current = []
        micRef.current = await startMic({ channels: 1, onFrame: (pcm) => chunks.current.push(pcm) })
      } else {
        const finalTranscripts: string[] = []
        speechRef.current = startWebSpeech({
          onResult: (text, isFinal) => {
            if (!isFinal) { onInterim?.(text); return }
            finalTranscripts.push(text)
            onText(text)
            // Известен только финальный текст: длительность аудио и средняя уверенность не измерены.
            onVoice?.({ stt_provider: 'browser', transcript_raw: finalTranscripts.join(' ') })
          },
          onError: (e) => e !== 'no-speech' && setErr(e),
        })
      }
      setRec(true)
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    }
  }
  const stop = async () => {
    setRec(false)
    if (mode === 'browser') {
      speechRef.current?.stop()
      speechRef.current = null
      return
    }
    micRef.current?.stop()
    micRef.current = null
    const total = Math.min(chunks.current.reduce((a, b) => a + b.byteLength, 0), Math.floor(maxSeconds * 16000) * 2)
    if (!total) return
    const buf = new Uint8Array(total)
    let off = 0
    for (const c of chunks.current) {
      const part = new Uint8Array(c).subarray(0, total - off)
      buf.set(part, off)
      off += part.byteLength
      if (off === total) break
    }
    setBusy(true)
    try {
      const r = await fetch('/api/stt/transcribe?sample_rate=16000', { method: 'POST', headers: { 'content-type': 'application/octet-stream' }, body: buf })
      const d = (await r.json()) as { ok?: boolean; text?: string; detail?: string; title?: string; provider?: Schemas['VoiceMeta']['stt_provider']; latency_ms?: number }
      if (!r.ok) throw new Error(d.detail ?? d.title ?? `HTTP ${r.status}`)
      if (d.text) {
        onText(d.text)
        if (d.provider) onVoice?.({ stt_provider: d.provider, transcript_raw: d.text, duration_ms: Math.round(total / 32), latency_ms: d.latency_ms })
      }
      else setErr(t('voice.nothing'))
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }
  stopRef.current = stop
  return (
    <span className={clsx('inline-flex items-center gap-1', className)}>
      <button
        type="button"
        className={clsx('btn btn-sm', rec && 'btn-danger')}
        disabled={busy}
        title={t(mode === 'server' ? 'voice.hintServer' : 'voice.hintBrowser')}
        onClick={() => (rec ? void stop() : void start())}
      >
        {rec ? <Square size={14} /> : <Mic size={14} />} {busy ? t('voice.busy') : rec ? t('voice.stop') : t('voice.start')}
      </button>
      {selected?.external_service && <span className="text-xs text-muted">{t('voice.externalHint')}</span>}
      {err && <span className="text-xs text-danger">{err}</span>}
    </span>
  )
}
