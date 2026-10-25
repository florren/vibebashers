import type { components, paths } from './types'

export type Schemas = components['schemas']
export type Signal = Schemas['Signal']
export type SignalDetail = Schemas['SignalDetail']
export type IncidentBrief = Schemas['IncidentBrief']
export type IncidentDetail = Schemas['IncidentDetail']
export type HitlItem = Schemas['HitlItem']
export type AgentRunBrief = Schemas['AgentRunBrief']
export type AgentRunDetail = Schemas['AgentRunDetail']
export type AgentStep = Schemas['AgentStep']
export type AgentGraph = Schemas['AgentGraph']
export type SimState = Schemas['SimState']
export type ClientBrief = Schemas['ClientBrief']
export type SimRun = Schemas['SimRun']
export type Notification = Schemas['Notification']
export type StatusHistoryItem = Schemas['StatusHistoryItem']
export type Decision = Schemas['decision.schema']
export type Classification = Schemas['classification.schema']
export type DecisionChain = Schemas['decision_chain.schema']
export type Task = Schemas['Task']
export type Followup = Schemas['Followup']
export type TranscriptBrief = Schemas['TranscriptBrief']
export type QualityReport = Schemas['QualityReport']
export type TranscriptDetail = Schemas['TranscriptDetail']
export type TranscriptReport = Schemas['TranscriptReport']
export type ExternalPost = Schemas['ExternalPost'] & { incident_id?: number | null; agent_run_id?: number | null; signal_type?: string | null; sentiment?: string | null }
export type ExternalPostDetail = ExternalPost & Schemas['ExternalPostDetail'] & { refunds?: Schemas['LedgerEntry'][]; incident_public_id?: string | null; incident_status?: string | null }
export type ExternalReply = Schemas['ExternalReply']
export type FeedStats = Schemas['FeedStats']
export type AccountsView = Schemas['AccountsView'] & { client?: Schemas['ClientBrief'] & { city_name?: string | null } }
export type LedgerEntry = Schemas['LedgerEntry']
export type BusinessRule = Schemas['BusinessRule']
export type RegionHeat = Schemas['RegionHeat'] & { name_ru?: string; district_code?: string; lat?: number; lon?: number }
export type CityHeat = Schemas['CityHeat'] & { population?: number }
export type MapZone = Schemas['MapZone']
export type MapZonesResponse = { thresholds?: Schemas['MapZoneThresholds']; no_geo_count?: number; items?: MapZone[] }
export type EconomicsGroup = NonNullable<Schemas['EconomicsSummary']['groups']>[number] & { at_risk_open_rub?: number }
export type EconomicsSummary = Omit<Schemas['EconomicsSummary'], 'groups'> & { refund_rub?: number; group_by?: string; groups?: EconomicsGroup[] }
export type DashboardMetrics = Schemas['DashboardMetrics'] & {
  run_id?: number | null
  signals_total?: number
  critical_total?: number
  agent_runs?: number
  agent_latency_p50_ms?: number
  tokens_total?: number
  incidents_total?: number
  incidents_open?: number
  sla_overdue_count?: number
  churned_clients?: number
  retained_clients?: number
  economics?: EconomicsSummary
}
export type EconomicsFact = Schemas['EconomicsFact']
export type Ticket = Schemas['Ticket'] & { criticality?: string; incident_type?: string; sla_due_sim?: string | null; sla_breached?: boolean; primary_client_id?: number | null; client_name?: string | null; escalations_count?: number }
export type Escalation = Schemas['Escalation'] & { incident_title?: string | null; incident_status?: string | null; team_code?: string | null; criticality?: string | null; client_name?: string | null; client_segment?: string | null; channel?: string | null }
export type EscalationDetail = Escalation & Schemas['EscalationDetail'] & { human_decision?: Record<string, unknown> | null }
export type TicketDetail = Ticket & Schemas['TicketDetail'] & { history?: StatusHistoryItem[] }
export type TeamLoad = Schemas['TeamLoad'] & { name_ru?: string; lead_display_name?: string | null; critical_open?: number; total?: number }
export type IncidentAction = NonNullable<paths['/api/incidents/{id}/actions']['post']['requestBody']>['content']['application/json'] & { actor?: string }
export type EscalationCreate = NonNullable<paths['/api/escalations']['post']['requestBody']>['content']['application/json'] & { actor?: string }
export type EscalationAck = NonNullable<paths['/api/escalations/{id}/ack']['post']['requestBody']>['content']['application/json']
export type NotificationItem = Schemas['Notification'] & { team_code?: string | null; signal_id?: number | null; client_name?: string | null; segment_code?: string | null; incident_public_id?: string | null }
export type ComplianceAlert = Schemas['ComplianceAlert'] & { kind?: 'threshold' | 'immediate' | 'report'; patterns?: string[]; transcript_id?: number | null; trigger_count?: number }
export type AudioSession = Schemas['AudioSession']
export type AudioSessionDetail = Schemas['AudioSessionDetail']
export type MissellingPattern = Schemas['MissellingPattern']
export type ComplianceEmployeeStats = Schemas['ComplianceEmployeeStats']
export type Problem = { type?: string; title?: string; status?: number; detail?: string; card?: string }

export type SimControl = NonNullable<paths['/api/sim/control']['post']['requestBody']>['content']['application/json']
export type HitlDecision = NonNullable<paths['/api/hitl/{id}']['post']['requestBody']>['content']['application/json']
export type JuryPayload = NonNullable<paths['/api/signals']['post']['requestBody']>['content']['application/json']
export type JuryResult = paths['/api/signals']['post']['responses'][202]['content']['application/json']

export class ApiError extends Error {
  status: number
  problem: Problem | null
  constructor(status: number, problem: Problem | null, fallback: string) {
    super(problem?.detail ?? problem?.title ?? fallback)
    this.status = status
    this.problem = problem
  }
  /** 501 — эндпоинт описан в OpenAPI, но карточка ещё не реализована (ответ Problem содержит card). */
  get notImplemented(): boolean {
    return this.status === 501
  }
}

export type Query = Record<string, string | number | boolean | string[] | null | undefined>

export function qs(params?: Query): string {
  if (!params) return ''
  const u = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === '') continue
    if (Array.isArray(v)) v.forEach((x) => u.append(k, x))
    else u.set(k, String(v))
  }
  const s = u.toString()
  return s ? `?${s}` : ''
}

export async function api<T>(path: string, init?: RequestInit & { query?: Query }): Promise<T> {
  const { query, ...rest } = init ?? {}
  const res = await fetch(`${path}${qs(query)}`, {
    ...rest,
    headers: { Accept: 'application/json, text/markdown', ...(rest.body ? { 'Content-Type': 'application/json' } : {}), ...rest.headers },
  })
  if (!res.ok) {
    let problem: Problem | null = null
    try {
      problem = (await res.json()) as Problem
    } catch {
      problem = null
    }
    throw new ApiError(res.status, problem, `${res.status} ${res.statusText}`)
  }
  if (res.status === 204) return undefined as T
  const ct = res.headers.get('content-type') ?? ''
  if (ct.includes('json')) return (await res.json()) as T
  return (await res.text()) as unknown as T
}

export const post = <T>(path: string, body: unknown, query?: Query) => api<T>(path, { method: 'POST', body: JSON.stringify(body), query })
export const put = <T>(path: string, body: unknown) => api<T>(path, { method: 'PUT', body: JSON.stringify(body) })
export const patch = <T>(path: string, body: unknown) => api<T>(path, { method: 'PATCH', body: JSON.stringify(body) })
export const del = <T>(path: string) => api<T>(path, { method: 'DELETE' })

// ---- T-009/T-010: мастер настройки ----
export type SetupStatus = paths['/api/setup/status']['get']['responses']['200']['content']['application/json']
export type SetupPayload = Schemas['SetupPayload'] & { economics?: EconomicsSettingsT }
export type DcltvRate = NonNullable<Schemas['EconomicsSettings']['rates']>[number]
export type EconomicsSettingsT = Omit<Schemas['EconomicsSettings'], 'rates'> & { rates?: DcltvRate[]; updated_at?: string }
export type SlaCell = Schemas['SlaCell']
export type RoutingRule = Schemas['RoutingRule']
export type LlmProfileT = Schemas['LlmProfile']
export type LlmApiKey = Schemas['LlmApiKey'] & { key_hint?: string }
export type GiftCatalogItem = Schemas['GiftCatalogItem']
export type NotificationTemplateT = Schemas['NotificationTemplate']
export type PsychotypeSettings = Schemas['PsychotypeSettings']
export type TestLlmResult = paths['/api/setup/test-llm']['post']['responses']['200']['content']['application/json']
export type TestLlmBody = NonNullable<paths['/api/setup/test-llm']['post']['requestBody']>['content']['application/json']
export type GenerateStatus = paths['/api/setup/generate']['get']['responses']['200']['content']['application/json']
export type GenerateBody = NonNullable<paths['/api/setup/generate']['post']['requestBody']>['content']['application/json'] & { reset_history?: boolean; clients?: number | null }

export type TaskItem = {
  id: number
  run_id: number
  kind: 'gift' | 'callback' | 'manual_review' | 'clarify_client' | 'report_reminder' | 'closure_review'
  incident_id: number | null
  assignee: string | null
  payload: Record<string, unknown> & { gift?: { gift_code?: string; points?: number; privilege_code?: string | null; when?: string }; issued?: { label: string }; decision?: { action: string; comment?: string | null } }
  status: 'open' | 'approved' | 'changed' | 'rejected' | 'done' | 'cancelled'
  requires_hitl: boolean
  due_sim: string | null
  created_sim: string | null
  resolved_sim: string | null
  incident_public_id: string | null
  incident_title: string | null
  incident_status: string | null
  incident_criticality: string | null
  gift_name: string | null
  ready: boolean
  overdue: boolean
  client: ClientBrief | null
}
export type TaskList = { items: TaskItem[]; next_cursor: string | null; counts: Record<string, number> }

export type EnvVar = Schemas['EnvVar']
export type EnvUpdate = Schemas['EnvUpdate']
export type EnvResult = Schemas['EnvResult']
export type EnvState = { path: string; exists: boolean; writable: boolean; items: EnvVar[] }

export type Branch = Schemas['Branch']
export type SttProvider = Schemas['SttProvider']
export type MicSession = AudioSession & { audio_ws_url: string; sample_rate: number; channels: 1 | 2 }
export type DemoStatus = Schemas['DemoStatus']
export type DemoFailoverBody = NonNullable<paths['/api/demo/failover']['post']['requestBody']>['content']['application/json']
export type DemoPlayBody = NonNullable<paths['/api/demo/play/{scenario_id}']['post']['requestBody']>['content']['application/json']
export type DemoPlayResult = paths['/api/demo/play/{scenario_id}']['post']['responses'][202]['content']['application/json']

export type SttMessage = {
  type: 'ready' | 'partial' | 'final' | 'error' | 'closed' | 'pong'
  session_id: number
  channel?: number
  text?: string
  seq?: number | null
  latency_ms?: number | null
  provider?: string | null
  error?: string | null
  model?: string | null
  diarization_mode?: string
  session_public_id?: string
  utterance?: { utterance_id: number; seq: number; speaker: 'employee' | 'client' | 'unknown'; speaker_confidence: number; speaker_source: string; text: string; t0_ms: number; t1_ms: number }
  trigger?: { id: number; pattern_code: string; confidence: number; quote: string; explanation_ru: string; recommendation_ru: string; status: string } | null
  session?: { trigger_count: number; status: string; alert_threshold: number }
  report?: Record<string, unknown> & { findings?: Array<{ turn_seq: number; pattern_code: string; family: string; confidence: number; quote: string; explanation_ru: string; recommendation_ru?: string }>; overall_ru?: string; confidence?: number }
}
