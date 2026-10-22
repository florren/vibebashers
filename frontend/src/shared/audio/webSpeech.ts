/** Web Speech API (Chrome/Edge): распознаёт браузер, на сервер уходит только текст (провайдер STT «browser»). */

type SRResultEvent = Event & { resultIndex: number; results: ArrayLike<{ isFinal: boolean; 0: { transcript: string; confidence: number } }> }
type SR = EventTarget & {
  lang: string
  continuous: boolean
  interimResults: boolean
  start: () => void
  stop: () => void
  abort: () => void
  onresult: ((e: SRResultEvent) => void) | null
  onerror: ((e: Event & { error?: string }) => void) | null
  onend: (() => void) | null
}

function ctor(): (new () => SR) | null {
  const w = window as unknown as { SpeechRecognition?: new () => SR; webkitSpeechRecognition?: new () => SR }
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null
}

export const webSpeechSupported = (): boolean => typeof window !== 'undefined' && ctor() !== null

export function startWebSpeech(opts: { lang?: string; onResult: (text: string, isFinal: boolean) => void; onError?: (err: string) => void }): { stop: () => void } {
  const C = ctor()
  if (!C) throw new Error('Web Speech API недоступен')
  const rec = new C()
  rec.lang = opts.lang ?? 'ru-RU'
  rec.continuous = true
  rec.interimResults = true
  let active = true
  rec.onresult = (e) => {
    for (let i = e.resultIndex; i < e.results.length; i++) {
      const r = e.results[i]
      if (!r) continue
      opts.onResult(r[0].transcript.trim(), r.isFinal)
    }
  }
  rec.onerror = (e) => opts.onError?.(e.error ?? 'error')
  rec.onend = () => {
    if (active) {
      try {
        rec.start() // Chrome останавливает поток через ~60 с — перезапускаем
      } catch {
        /* уже стартует */
      }
    }
  }
  rec.start()
  return {
    stop: () => {
      active = false
      rec.stop()
    },
  }
}
