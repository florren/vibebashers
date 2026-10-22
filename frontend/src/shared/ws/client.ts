import { create } from 'zustand'
import type { QueryClient } from '@tanstack/react-query'
import type { SimState } from '@/shared/api/client'

/** Сообщение /ws/stream (contracts/events/ws/message.schema.json): topic/type/ts/data[/run_id]. */
export type WsMessage = { topic: string; type: string; ts: string; data: Record<string, unknown>; run_id?: number | null }

export type LiveEvent = WsMessage & { seq: number }

type WsStatus = 'connecting' | 'open' | 'closed'

type WsState = {
  status: WsStatus
  sim: SimState | null
  /** Последние события агента — для живой трассировки «Под капотом» и бейджей. */
  events: LiveEvent[]
  seq: number
  setSim: (s: SimState) => void
  push: (m: WsMessage) => void
  setStatus: (s: WsStatus) => void
}

const MAX_EVENTS = 400

export const useWs = create<WsState>((set) => ({
  status: 'connecting',
  sim: null,
  events: [],
  seq: 0,
  setSim: (sim) => set({ sim }),
  setStatus: (status) => set({ status }),
  push: (m) =>
    set((st) => {
      const seq = st.seq + 1
      const events = [{ ...m, seq }, ...st.events]
      if (events.length > MAX_EVENTS) events.length = MAX_EVENTS
      return { events, seq }
    }),
}))

export const TOPICS = ['signals', 'agent', 'incidents', 'notifications', 'hitl', 'tasks', 'sim', 'runs', 'escalations', 'tickets', 'compliance', 'ingest', 'feed', 'abs'] as const

/** Какие запросы инвалидировать по топику (ключи react-query). */
const INVALIDATE: Record<string, string[][]> = {
  signals: [['signals']],
  incidents: [['incidents']],
  agent: [['agent']],
  hitl: [['hitl'], ['signals']],
  notifications: [['notifications'], ['incidents']],
  tasks: [['tasks']],
  runs: [['sim-runs']],
  escalations: [['escalations']],
  tickets: [['tickets']],
  compliance: [['compliance'], ['transcripts']],
  ingest: [['transcripts']],
  feed: [['feed'], ['signals']],
  abs: [['abs'], ['feed']],
}

let socket: WebSocket | null = null
let timer: ReturnType<typeof setTimeout> | null = null
const pending = new Map<string, ReturnType<typeof setTimeout>>()

function wsUrl(): string {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${location.host}/ws/stream`
}

/** Один сокет на вкладку; автопереподключение с backoff; инвалидация запросов с троттлингом 250 мс по топику. */
export function connectWs(qc: QueryClient): () => void {
  let backoff = 1000
  let closedByUs = false

  const invalidate = (topic: string) => {
    const keys = INVALIDATE[topic]
    if (!keys || pending.has(topic)) return
    pending.set(
      topic,
      setTimeout(() => {
        pending.delete(topic)
        keys.forEach((k) => void qc.invalidateQueries({ queryKey: k }))
      }, 250),
    )
  }

  const open = () => {
    useWs.getState().setStatus('connecting')
    const ws = new WebSocket(wsUrl())
    socket = ws
    ws.onopen = () => {
      backoff = 1000
      useWs.getState().setStatus('open')
      ws.send(JSON.stringify({ type: 'subscribe', topics: [...TOPICS] }))
    }
    ws.onmessage = (ev) => {
      let m: WsMessage
      try {
        m = JSON.parse(String(ev.data)) as WsMessage
      } catch {
        return
      }
      if (m.topic === 'sim') {
        if (m.type === 'sim.tick' || m.type === 'sim.control') useWs.getState().setSim(m.data as SimState)
        if (m.type === 'sim.control') void qc.invalidateQueries({ queryKey: ['sim-runs'] })
        return
      }
      if (m.topic === 'system') return
      useWs.getState().push(m)
      invalidate(m.topic)
    }
    ws.onclose = () => {
      useWs.getState().setStatus('closed')
      if (closedByUs) return
      timer = setTimeout(open, backoff)
      backoff = Math.min(backoff * 2, 15000)
    }
    ws.onerror = () => ws.close()
  }
  open()
  return () => {
    closedByUs = true
    if (timer) clearTimeout(timer)
    socket?.close()
    socket = null
  }
}
