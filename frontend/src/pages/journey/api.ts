import { api, type Schemas, type SignalDetail, type AgentRunDetail, type IncidentDetail } from '@/shared/api/client'
import i18n from '@/shared/i18n'
import type { paths } from '@/shared/api/types'

type IngestResponse = paths['/api/ingest/messages']['post']['responses'][202]['content']['application/json']
type UnifiedMessage = Schemas['unified_message.schema']

export async function sendJourneyMessage(body: UnifiedMessage) {
  const response = await api<IngestResponse>('/api/ingest/messages', { method: 'POST', headers: { 'X-Source-Code': 'journey' }, body: JSON.stringify(body) })
  const item = response.items?.[0]
  if (!item?.signal_id || item.status === 'rejected') throw new Error(item?.error ?? i18n.t('journeyLive.sendError'))
  return item.signal_id
}

// public_id создаётся из PK в schema.sql; произвольные tracking-токены здесь не разбираем.
export function numericRef(ref: string | undefined, prefix: string): number | null {
  const match = ref?.match(new RegExp(`^${prefix}-(\\d+)$`, 'i'))
  return match && Number.isSafeInteger(Number(match[1])) ? Number(match[1]) : null
}
export const loadSignal = (id: number) => api<SignalDetail>(`/api/signals/${id}`)
export const loadRun = (id: number) => api<AgentRunDetail>(`/api/agent/runs/${id}`)
export const loadClient = (id: number) => api<Schemas['Client360']>(`/api/clients/${id}/360`)
export const loadEconomics = (id: number) => api<Schemas['IncidentEconomics']>(`/api/incidents/${id}/economics`)
export const recoverJourneyCase = (id: number) => api(`/api/demo/incidents/${id}/recover`, { method: 'POST' })
export async function loadRecoveryIncident(id: number): Promise<{ canRecover: boolean; status?: IncidentDetail['status'] }> {
  const [incident, artifacts] = await Promise.all([
    api<IncidentDetail>(`/api/incidents/${id}`),
    api<Schemas['Artifact'][]>(`/api/incidents/${id}/artifacts`),
  ])
  return { canRecover: incident.status === 'escalated' && artifacts.some(a => a.meta?.outcome === 'failed'), status: incident.status }
}

/** Открывает существующую запись сценария, никогда не запускает сценарий заново. */
export async function loadScenarioJourney(scenarioId: string) {
  const runs = await api<paths['/api/sim/runs']['get']['responses'][200]['content']['application/json']>('/api/sim/runs', { query: { limit: 500 } })
  const run = (runs.items ?? []).find((r) => r.scenario_id === scenarioId)
  if (!run) throw new Error(i18n.t('journeyModes.noScenario'))
  const journey = await api<import('@/shared/api/trace').Journey>('/api/journey/latest', { query: { origin: 'sim', run_id: run.id } })
  if (!journey.stages.some((s) => s.events.some((e) => numericRef(e.run_id ?? undefined, 'SR') === run.id))) throw new Error(i18n.t('journeyModes.noScenario'))
  return journey.subject.ref
}

/** Сохраняет явный run при переходе из аналитики; legacy href не меняется. */
export function scopedJourneyHref(path: string, runId?: string): string {
  if (runId === undefined) return path
  const url = new URL(path, 'http://cx.local')
  url.searchParams.set('run_id', runId)
  return url.pathname + url.search + url.hash
}
