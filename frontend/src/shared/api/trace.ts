import type { components, paths } from './types'
import { api } from './client'
export type Trace = components['schemas']['trace_response.schema']
export type TraceEvent = components['schemas']['trace_event.schema']
// $defs is JSON Schema metadata emitted as a required TS property by openapi-typescript.
export type Journey = Omit<components['schemas']['journey.schema'], '$defs'>
export type Search = components['schemas']['search_response.schema']
export type TraceRelationPage = components['schemas']['trace_relation_page.schema']
export type TraceQuery = paths['/api/trace/{kind}/{ref}']['get']['parameters']['query']
export type RelationQuery = paths['/api/trace/{kind}/{ref}/relations']['get']['parameters']['query']
export const getTrace = (kind: string, ref: string, query?: TraceQuery) => api<Trace>(`/api/trace/${encodeURIComponent(kind)}/${encodeURIComponent(ref)}`, { query })
export const getTraceRelations = (kind: string, ref: string, query: RelationQuery) =>
  api<TraceRelationPage>(`/api/trace/${encodeURIComponent(kind)}/${encodeURIComponent(ref)}/relations`, { query })
export const getJourney = (ref?: string, origin: 'jury' | 'feed' | 'sim' | 'any' = 'jury', presenter = false) =>
  api<Journey>(ref ? `/api/journey/${encodeURIComponent(ref)}` : '/api/journey/latest', {
    query: { run_id: ref ? 'all' : 'current', ...(!ref ? { origin } : {}), ...(presenter ? { presenter: 1 } : {}) },
  })
export const searchObjects = (q: string, signal?: AbortSignal) => api<Search>('/api/search', { query: { q }, signal })
