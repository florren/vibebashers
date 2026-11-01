import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { clsx } from 'clsx'
import { Mic, Square } from 'lucide-react'
import { useSttProviders } from '@/shared/api/hooks'
import { micSupported, startMic, type MicHandle } from './mic'
import { startWebSpeech, webSpeechSupported } from './webSpeech'

/** «Надиктовать» (T-206): офлайн — пишем PCM16 и отправляем в POST /api/stt/transcribe (Vosk); иначе — Web Speech API браузера. */
export function VoiceInput({ onText, onInterim, className, serverOnly = false, maxSeconds = 120 }: { onText: (text: string) => void; onInterim?: (text: string) => void; className?: string; serverOnly?: boolean; maxSeconds?: number }) {
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
  const speechRef = useRef<{ stop: () => void } | null>(null)
  const serverOk = (prov.data ?? []).some((p) => p.available && p.code !== 'browser') && micSupported()
  const mode: 'server' | 'browser' | null = serverOk ? 'server' : !serverOnly && webSpeechSupported() ? 'browser' : null

  useEffect(() => () => {
    micRef.current?.stop()
    speechRef.current?.stop()
  }, [])
  if (!mode) return null

  const start = async () => {
    setErr(null)
    try {
      if (mode === 'server') {
        chunks.current = []
        micRef.current = await startMic({ channels: 1, onFrame: (pcm) => chunks.current.push(pcm) })
      } else {
        speechRef.current = startWebSpeech({
          onResult: (text, isFinal) => (isFinal ? onText(text) : onInterim?.(text)),
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
      const d = (await r.json()) as { ok?: boolean; text?: string; detail?: string; title?: string }
      if (!r.ok) throw new Error(d.detail ?? d.title ?? `HTTP ${r.status}`)
      if (d.text) onText(d.text)
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
      {err && <span className="text-xs text-danger">{err}</span>}
    </span>
  )
}
