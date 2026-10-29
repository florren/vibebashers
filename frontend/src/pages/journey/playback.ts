import type { Journey, TraceEvent } from '@/shared/api/trace'

export type JourneyMode = 'follow' | 'replay' | 'presenter'
export type Playback = { cursor: number; playing: boolean; tempo: 'real' | 'compressed' }
export type PlaybackAction =
  | { type: 'play' | 'pause' | 'reset' }
  | { type: 'step'; delta: number; length: number }
  | { type: 'tempo'; value: Playback['tempo'] }
export const initialPlayback: Playback = { cursor: -1, playing: false, tempo: 'compressed' }
export function playbackReducer(state: Playback, action: PlaybackAction): Playback {
  switch (action.type) {
    case 'play':
      return { ...state, playing: true }
    case 'pause':
      return { ...state, playing: false }
    case 'reset':
      return { ...initialPlayback, tempo: state.tempo }
    case 'tempo':
      return { ...state, tempo: action.value }
    case 'step': {
      const cursor = Math.max(-1, Math.min(action.length - 1, state.cursor + action.delta))
      return { ...state, cursor, playing: action.delta === 1 && cursor < action.length - 1 ? state.playing : false }
    }
  }
}
export type Frame = { at: number; event?: TraceEvent; stage?: string; message?: Journey['client_lane'][number] }
/** Порядок по реальным часам; при одинаковой метке сохраняется серверный порядок. */
export function timeline(data: Journey): Frame[] {
  return [
    ...data.stages.flatMap((s) => s.events.map((event) => ({ at: Date.parse(event.ts_real) || 0, event, stage: s.stage }))),
    ...data.client_lane.map((message) => ({ at: Date.parse(message.delivered_at) || 0, message })),
  ].sort((a, b) => a.at - b.at)
}
export function frameDelay(frames: Frame[], cursor: number, tempo: Playback['tempo']): number {
  if (cursor < 0) return 0
  const delta = Math.max(0, (frames[cursor + 1]?.at ?? 0) - (frames[cursor]?.at ?? 0))
  return tempo === 'real' ? delta : Math.max(250, Math.min(2000, delta / 30))
}
export function visibleJourney(data: Journey, frames: Frame[], cursor: number): Journey {
  const visible = frames.slice(0, cursor + 1)
  const ids = new Set(visible.flatMap((f) => (f.event ? [f.event.id] : [])))
  const messages = new Set(visible.flatMap((f) => (f.message ? [f.message] : [])))
  const active = [...visible].reverse().find((f) => f.stage)?.stage
  const finished = cursor >= frames.length - 1 && frames.length > 0
  return {
    ...data,
    stages: data.stages.map((s) => ({
      ...s,
      events: s.events.filter((e) => ids.has(e.id)),
      status: finished ? s.status : s.stage === active ? 'active' : s.events.some((e) => ids.has(e.id)) ? 'done' : 'pending',
    })),
    client_lane: data.client_lane.filter((m) => messages.has(m)),
  }
}
/** T-223 передаёт заметки ведущего в key_facts, отдельного поля в контракте нет. */
export function presenterNotes(events: TraceEvent[]): string[] {
  return [...new Set(events.flatMap((e) => e.key_facts.filter((f) => f.label_ru === 'Заметка ведущего').map((f) => f.value_ru)))]
}
