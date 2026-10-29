import { expect, it } from 'vitest'
import { frameDelay, initialPlayback, playbackReducer, presenterNotes, timeline, visibleJourney } from '../playback'

import { recording } from './recordings'
it('bounds backward/forward steps, pauses at end and resets without changing pace', () => {
  let state = playbackReducer(initialPlayback, { type: 'play' })
  state = playbackReducer(state, { type: 'step', delta: 1, length: 2 })
  expect(state).toMatchObject({ cursor: 0, playing: true })
  state = playbackReducer(state, { type: 'step', delta: 1, length: 2 })
  expect(state).toMatchObject({ cursor: 1, playing: false })
  expect(playbackReducer(state, { type: 'step', delta: 9, length: 2 }).cursor).toBe(1)
  expect(playbackReducer(state, { type: 'step', delta: -9, length: 2 }).cursor).toBe(-1)
  expect(playbackReducer({ ...state, tempo: 'real' }, { type: 'reset' })).toEqual({ ...initialPlayback, tempo: 'real' })
})
it.each([1, 8, 11] as const)('scenario %i snapshot reveals and rewinds only recorded events and delivered messages', (scenario) => {
  const data = recording(scenario),
    saved = JSON.stringify(data),
    frames = timeline(data)
  expect(frames).toHaveLength(3)
  expect(visibleJourney(data, frames, -1).stages.every((s) => s.status === 'pending')).toBe(true)
  expect(visibleJourney(data, frames, 0).client_lane).toHaveLength(0)
  expect(visibleJourney(data, frames, 1).stages[4]!.events).toHaveLength(1)
  expect(visibleJourney(data, frames, 2).client_lane).toHaveLength(1)
  expect(visibleJourney(data, frames, 0).stages[4]!.events).toHaveLength(0)
  expect(frameDelay(frames, 0, 'real')).toBe(60000)
  expect(frameDelay(frames, 0, 'compressed')).toBe(2000)
  expect(presenterNotes(data.stages[0]!.events)).toEqual([`Тезис сценария ${scenario}`])
  expect(JSON.stringify(data)).toBe(saved)
})
it('preserves stable order for identical timestamps and does not use simulated clock for pacing', () => {
  const data = recording(8)
  data.stages[4]!.events[0]!.ts_real = data.stages[0]!.events[0]!.ts_real
  const frames = timeline(data)
  expect(frames.slice(0, 2).map((f) => f.event?.id)).toEqual(['intake', 'decision'])
  expect(frameDelay(frames, 0, 'real')).toBe(0)
  expect(frameDelay(frames, -1, 'compressed')).toBe(0)
})
