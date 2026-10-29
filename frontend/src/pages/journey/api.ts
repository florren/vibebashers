import { api, post, type Schemas, type SignalDetail, type AgentRunDetail } from '@/shared/api/client'
import i18n from '@/shared/i18n'
import type { paths } from '@/shared/api/types'

type IngestResponse = paths['/api/ingest/messages']['post']['responses'][202]['content']['application/json']
type UnifiedMessage = Schemas['unified_message.schema']

export async function sendJourneyMessage(body: UnifiedMessage) {
  const response = await post<IngestResponse>('/api/ingest/messages', body)
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
