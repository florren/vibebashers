import type { components } from './types'
import { api } from './client'
export type Trace = components['schemas']['trace_response.schema']
export type TraceEvent = components['schemas']['trace_event.schema']
// $defs is JSON Schema metadata emitted as a required TS property by openapi-typescript.
export type Journey = Omit<components['schemas']['journey.schema'], '$defs'>
export type Search = components['schemas']['search_response.schema']
export const getTrace = (kind: string, ref: string) => api<Trace>(`/api/trace/${encodeURIComponent(kind)}/${encodeURIComponent(ref)}`)
export const getJourney = (ref?: string, origin: 'jury' | 'feed' | 'sim' | 'any' = 'jury') =>
  api<Journey>(ref ? `/api/journey/${encodeURIComponent(ref)}` : '/api/journey/latest', {
    query: { run_id: ref ? 'all' : 'current', ...(!ref ? { origin } : {}) },
  })
export const searchObjects = (q: string, signal?: AbortSignal) => api<Search>('/api/search', { query: { q }, signal })
