import type { Schemas } from './client'
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  api,
  ApiError,
  post,
  type AccountsView,
  type AgentGraph,
  type BusinessRule,
  type CityHeat,
  type DashboardMetrics,
  type EconomicsFact,
  type EconomicsSettingsT,
  type GenerateBody,
  type GenerateStatus,
  type GiftCatalogItem,
  type LlmApiKey,
  type LlmProfileT,
  type NotificationTemplateT,
  type PsychotypeSettings,
  type RoutingRule,
  type SetupPayload,
  type SetupStatus,
  type SlaCell,
  type TestLlmBody,
  type TestLlmResult,
  del,
  patch,
  put,
  type Escalation,
  type EscalationAck,
  type EscalationCreate,
  type EscalationDetail,
  type IncidentAction,
  type TeamLoad,
  type TaskItem,
  type EnvResult,
  type Branch,
  type MicSession,
  type SttProvider,
  type EnvState,
  type EnvUpdate,
  type TaskList,
  type Ticket,
  type TicketDetail,
  type EconomicsSummary,
  type MapZonesResponse,
  type NotificationItem,
  type RegionHeat,
  type ExternalPost,
  type ExternalPostDetail,
  type ExternalReply,
  type FeedStats,
  type AudioSessionDetail,
  type ComplianceAlert,
  type ComplianceEmployeeStats,
  type MissellingPattern,
  type Problem,
  type QualityReport,
  type TranscriptBrief,
  type TranscriptDetail,
  type TranscriptReport,
  type AgentRunBrief,
  type AgentRunDetail,
  type ClientBrief,
  type DecisionChain,
  type DemoFailoverBody,
  type DemoPlayBody,
  type DemoPlayResult,
  type DemoStatus,
  type BenchDatasets,
  type BenchRun,
  type BenchRunAccepted,
  type BenchRunCreate,
  type BenchRunDetail,
  type SentimentBenchReport,
  type Followup,
  type HitlDecision,
  type HitlItem,
  type IncidentBrief,
  type IncidentDetail,
  type JuryPayload,
  type JuryResult,
  type Notification,
  type Query,
  type Signal,
  type SignalDetail,
  type SimControl,
  type SimRun,
  type SimState,
  type StatusHistoryItem,
} from './client'

type List<T> = { items?: T[]; next_cursor?: string | null }

export type RefRow = { code: string; name_ru: string; name_en?: string } & Record<string, unknown>

export const useRefs = (name: string) => useQuery({ queryKey: ['refs', name], queryFn: () => api<RefRow[]>(`/api/refs/${name}`), staleTime: Infinity })

/** code → name_ru по справочнику; фолбэк — код. */
export function useRefName(name: string): (code: string | null | undefined) => string {
  const q = useRefs(name)
  const map = new Map((q.data ?? []).map((r) => [r.code, r.name_ru]))
  return (code) => (code ? (map.get(code) ?? code) : '—')
}

/** Поиск клиентов для режима жюри (сегмент/строка). */
export const useClients = (params: { segment?: string; q?: string }, enabled = true) =>
  useQuery({
    queryKey: ['clients', params],
    queryFn: () => api<ClientBrief[]>('/api/clients', { query: { ...params, limit: 30 } }),
    enabled,
    staleTime: 60_000,
  })

export const useSimState = () => useQuery({ queryKey: ['sim-state'], queryFn: () => api<SimState>('/api/sim/state'), refetchInterval: 15000 })
export const useSimRuns = () => useQuery({ queryKey: ['sim-runs'], queryFn: () => api<List<SimRun>>('/api/sim/runs', { query: { limit: 20 } }) })

export function useSimControl() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: SimControl) => post<SimState>('/api/sim/control', body),
    onSuccess: (s) => {
      qc.setQueryData(['sim-state'], s)
      void qc.invalidateQueries({ queryKey: ['sim-runs'] })
    },
  })
}

export const useSignals = (query: Query) =>
  useQuery({ queryKey: ['signals', 'list', query], queryFn: () => api<List<Signal>>('/api/signals', { query }), placeholderData: (p) => p })
export const useSignalPages = (query: Query) => useInfiniteQuery({
  queryKey: ['signals', 'pages', query], refetchInterval: 5000, initialPageParam: null as string | null,
  queryFn: ({ pageParam }) => api<List<Signal>>('/api/signals', { query: { ...query, cursor: pageParam } }),
  getNextPageParam: page => page.next_cursor ?? undefined,
})
export const useHitlPages = (query: Query) => useInfiniteQuery({
  queryKey: ['hitl', 'pages', query], refetchInterval: 5000, initialPageParam: null as string | null,
  queryFn: ({ pageParam }) => api<Schemas['HitlList']>('/api/hitl/queue', { query: { ...query, cursor: pageParam } }),
  getNextPageParam: page => page.next_cursor ?? undefined,
})
export const useHitlFeedback = (id: number | undefined) => useInfiniteQuery({
  queryKey: ['hitl', 'feedback', id], initialPageParam: null as string | null, enabled: id !== undefined,
  queryFn: ({ pageParam }) => api<Schemas['HitlFeedbackList']>(`/api/hitl/${id}/feedback`, { query: { cursor: pageParam } }),
  getNextPageParam: page => page.next_cursor ?? undefined,
})
export const useSignal = (id: number | null) =>
  useQuery({ queryKey: ['signals', 'one', id], queryFn: () => api<SignalDetail>(`/api/signals/${id}`), enabled: id !== null })
export const useDeferred = (query: Query) =>
  useQuery({ queryKey: ['signals', 'deferred', query], queryFn: () => api<List<Followup & { signal?: Signal }>>('/api/signals/deferred', { query }) })

export const useIncidents = (query: Query) =>
  useQuery({ queryKey: ['incidents', 'list', query], queryFn: () => api<List<IncidentBrief>>('/api/incidents', { query }), placeholderData: (p) => p })
export const useIncident = (id: number | null) =>
  useQuery({ queryKey: ['incidents', 'one', id], queryFn: () => api<IncidentDetail>(`/api/incidents/${id}`), enabled: id !== null })
export const useIncidentHistory = (id: number | null) =>
  useQuery({
    queryKey: ['incidents', 'history', id],
    queryFn: () => api<List<StatusHistoryItem> | StatusHistoryItem[]>(`/api/incidents/${id}/history`),
    enabled: id !== null,
  })
export const useIncidentSignals = (id: number | null) =>
  useQuery({
    queryKey: ['incidents', 'signals', id],
    queryFn: () => api<{ signals?: Signal[]; system_logs?: Record<string, unknown>[] } & List<Signal>>(`/api/incidents/${id}/signals`),
    enabled: id !== null,
  })
export const useIncidentComms = (id: number | null) =>
  useQuery({
    queryKey: ['incidents', 'comms', id],
    queryFn: () => api<List<Notification> | Notification[]>(`/api/incidents/${id}/communications`),
    enabled: id !== null,
  })

export const useHitlQueue = (query: Query) =>
  useQuery({ queryKey: ['hitl', 'queue', query], queryFn: () => api<Schemas['HitlList']>('/api/hitl/queue', { query }), refetchInterval: 5000, placeholderData: (p) => p })
export const useHitlItem = (id: number | null) =>
  useQuery({ queryKey: ['hitl', 'one', id], queryFn: () => api<HitlItem>(`/api/hitl/${id}`), enabled: id !== null, refetchInterval: 5000 })
export function useHitlDecide() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, body }: { id: number; body: HitlDecision }) => post<HitlItem>(`/api/hitl/${id}`, body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['hitl'] })
      void qc.invalidateQueries({ queryKey: ['signals'] })
      void qc.invalidateQueries({ queryKey: ['incidents'] })
      void qc.invalidateQueries({ queryKey: ['agent'] })
    },
  })
}

export const useAgentRuns = (query: Query) =>
  useQuery({ queryKey: ['agent', 'runs', query], queryFn: () => api<List<AgentRunBrief>>('/api/agent/runs', { query }), placeholderData: (p) => p })
export const useAgentRun = (id: number | null) =>
  useQuery({ queryKey: ['agent', 'run', id], queryFn: () => api<AgentRunDetail>(`/api/agent/runs/${id}`), enabled: id !== null })
export const useAgentGraph = () => useQuery({ queryKey: ['agent', 'graph'], queryFn: () => api<AgentGraph>('/api/agent/graph'), staleTime: Infinity })
export const useDecisionChain = (id: number | null, format: 'json' | 'md') =>
  useQuery<string | DecisionChain>({
    queryKey: ['agent', 'chain', id, format],
    queryFn: async (): Promise<string | DecisionChain> =>
      format === 'md'
        ? api<string>(`/api/agent/runs/${id}/decision-chain`, { query: { format }, headers: { Accept: 'text/markdown' } })
        : api<DecisionChain>(`/api/agent/runs/${id}/decision-chain`, { query: { format } }),
    enabled: id !== null,
  })

export function useJury() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: JuryPayload) => post<JuryResult>('/api/signals', body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['signals'] })
      void qc.invalidateQueries({ queryKey: ['agent'] })
    },
  })
}

export function listItems<T>(d: List<T> | T[] | undefined): T[] {
  if (!d) return []
  return Array.isArray(d) ? d : (d.items ?? [])
}

// ---------------------------------------------------------------- B07: комплаенс и транскрипты
export const useTranscripts = (query: Query) =>
  useQuery({ queryKey: ['transcripts', query], queryFn: () => api<List<TranscriptBrief>>('/api/ingest/transcripts', { query }), refetchInterval: 4000 })
export const useTranscript = (id: number | null) =>
  useQuery({ queryKey: ['transcripts', 'one', id], queryFn: () => api<TranscriptDetail>(`/api/ingest/transcripts/${id}`), enabled: id != null, refetchInterval: 4000 })
export const useTranscriptReport = (id: number | null, enabled: boolean) =>
  useQuery({
    queryKey: ['transcripts', 'report', id],
    queryFn: () => api<TranscriptReport & { alerts?: ComplianceAlert[] }>(`/api/compliance/transcripts/${id}/report`),
    enabled: id != null && enabled,
    retry: false,
  })
export const useComplianceAlerts = (query: Query) =>
  useQuery({ queryKey: ['compliance', 'alerts', query], queryFn: () => api<ComplianceAlert[]>('/api/compliance/alerts', { query }), refetchInterval: 5000 })
export const useComplianceSession = (id: number | null) =>
  useQuery({ queryKey: ['compliance', 'session', id], queryFn: () => api<AudioSessionDetail>(`/api/compliance/sessions/${id}`), enabled: id != null })
export const useCompliancePatterns = () =>
  useQuery({ queryKey: ['compliance', 'patterns'], queryFn: () => api<MissellingPattern[]>('/api/compliance/patterns'), staleTime: 60_000 })
export const useComplianceStats = (query: Query) =>
  useQuery({ queryKey: ['compliance', 'stats', query], queryFn: () => api<ComplianceEmployeeStats[]>('/api/compliance/stats', { query }), refetchInterval: 10_000 })

export function useUploadTranscripts() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (files: File[]) => {
      const fd = new FormData()
      files.forEach((f) => fd.append('files', f))
      const res = await fetch('/api/ingest/transcripts', { method: 'POST', body: fd })
      if (!res.ok) throw new ApiError(res.status, (await res.json().catch(() => null)) as Problem | null, `${res.status}`)
      return (await res.json()) as { items: TranscriptBrief[] }
    },
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['transcripts'] }),
  })
}
export function useImportTranscripts() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => post<{ files_found: number; accepted: number; duplicates: number; rejected: number }>('/api/ingest/transcripts/import', {}),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['transcripts'] }),
  })
}
export function useAckAlert() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, decision, comment }: { id: number; decision: 'go' | 'false_positive' | 'open_incident'; comment?: string }) =>
      post<ComplianceAlert>(`/api/compliance/alerts/${id}/ack`, { decision, comment }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['compliance'] })
      void qc.invalidateQueries({ queryKey: ['incidents'] })
    },
  })
}
export function useSendReport() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id }: { id: number }) => post<{ notification_id: number; alert_id: number | null }>(`/api/compliance/transcripts/${id}/send`, { to_role: 'branch_manager' }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['compliance'] }),
  })
}

export const useQualityReport = (runId: 'all' | 'current') =>
  useQuery({ queryKey: ['reports', 'quality', runId], queryFn: () => api<QualityReport>('/api/reports/quality', { query: { run_id: runId } }), refetchInterval: 30_000 })

// --- B06/B16: публичная лента и Mock-АБС
export const useFeed = (query: Query) =>
  useQuery({
    queryKey: ['feed', 'list', query],
    queryFn: () => api<{ items: ExternalPost[]; next_cursor: string | null; total: number }>('/api/public/feed', { query }),
    refetchInterval: 4000,
  })
export const usePost = (id: number | null) =>
  useQuery({ queryKey: ['feed', 'post', id], queryFn: () => api<ExternalPostDetail>(`/api/public/feed/${id}`), enabled: id != null, refetchInterval: 4000 })
export const useFeedStats = (runId: 'all' | 'current') =>
  useQuery({ queryKey: ['feed', 'stats', runId], queryFn: () => api<FeedStats>('/api/feed/stats', { query: { run_id: runId } }), refetchInterval: 5000 })
export const useAbsAccounts = (clientId: number | null) =>
  useQuery({
    queryKey: ['abs', 'accounts', clientId],
    queryFn: () => api<AccountsView>(`/api/abs/accounts/${clientId}`, { query: { entries_limit: 25 } }),
    enabled: clientId != null,
    refetchInterval: 5000,
  })
export const useRules = () => useQuery({ queryKey: ['rules'], queryFn: () => api<BusinessRule[]>('/api/rules'), staleTime: 60_000 })
export function usePublishReview() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { platform: 'review_portal' | 'telegram_channel'; author_nick: string; text: string; mentions?: { card_last4?: string; city?: string } }) =>
      post<{ post_id: number; public_id: string; signal_id: number | null }>('/api/public/reviews', body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['feed'] })
      void qc.invalidateQueries({ queryKey: ['signals'] })
    },
  })
}
export function useManualReply() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, text }: { id: number; text: string }) => post<ExternalReply>(`/api/feed/${id}/reply`, { text }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['feed'] }),
  })
}

// ---- B08/B14: карта, метрики, уведомления ----
export type MapLayer = 'signals' | 'critical' | 'incidents' | 'churn'
export const useMapHeat = (layer: MapLayer, windowHours: number, runId: 'all' | 'current' = 'current') =>
  useQuery({
    queryKey: ['map', 'heat', layer, windowHours, runId],
    queryFn: () => api<RegionHeat[]>('/api/map/heat', { query: { layer, window_hours: windowHours, run_id: runId } }),
    refetchInterval: 10_000,
    placeholderData: (p) => p,
  })
export const useMapZones = (runId: 'all' | 'current' = 'current') =>
  useQuery({ queryKey: ['map', 'zones', runId], queryFn: () => api<MapZonesResponse>('/api/map/zones', { query: { run_id: runId } }), refetchInterval: 15_000 })
export const useMapCities = (code: string | null, windowHours: number, runId: 'all' | 'current' = 'current') =>
  useQuery({
    queryKey: ['map', 'cities', code, windowHours, runId],
    queryFn: () => api<CityHeat[]>(`/api/map/regions/${code}/cities`, { query: { window_hours: windowHours, run_id: runId } }),
    enabled: code !== null,
  })
export const useDashboard = (window: 'run' | '24h' | '7d' | 'all' = 'run') =>
  useQuery({ queryKey: ['metrics', 'dashboard', window], queryFn: () => api<DashboardMetrics>('/api/metrics/dashboard', { query: { window } }), refetchInterval: 8_000, placeholderData: (p) => p })
export const useEconomics = (groupBy: string, runId: 'all' | 'current' = 'current') =>
  useQuery({
    queryKey: ['metrics', 'economics', groupBy, runId],
    queryFn: () => api<EconomicsSummary>('/api/metrics/economics', { query: { group_by: groupBy, run_id: runId } }),
    refetchInterval: 10_000,
    placeholderData: (p) => p,
  })
export const useEconomicsFact = (enabled: boolean) =>
  useQuery({ queryKey: ['metrics', 'fact'], queryFn: () => api<EconomicsFact>('/api/metrics/economics/fact'), enabled, refetchInterval: 15_000 })
export function useCalibrate() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (mode: 'manual' | 'simulated') => post<{ calibration_mode: string; recomputed: number }>('/api/metrics/economics/calibrate', { mode }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['metrics'] }),
  })
}
export const useNotifications = (query: Query) =>
  useQuery({
    queryKey: ['notifications', 'list', query],
    queryFn: () => api<List<NotificationItem>>('/api/notifications', { query }),
    refetchInterval: 6_000,
    placeholderData: (p) => p,
  })

// ---- B13: тикеты, эскалации, команды, действия оператора ----
export const useTickets = (query: Query) =>
  useQuery({
    queryKey: ['tickets', 'list', query],
    queryFn: () => api<List<Ticket> & { total?: number }>('/api/tickets', { query }),
    refetchInterval: 6_000,
    placeholderData: (p) => p,
  })
export const useTicket = (id: number | string | null) =>
  useQuery({ queryKey: ['tickets', 'one', id], queryFn: () => api<TicketDetail>(`/api/tickets/${id}`), enabled: id !== null })
export const useEscalations = (query: Query) =>
  useQuery({
    queryKey: ['escalations', 'list', query],
    queryFn: () => api<List<Escalation> & { counts?: Record<string, number> }>('/api/escalations', { query }),
    refetchInterval: 6_000,
    placeholderData: (p) => p,
  })
export const useEscalation = (id: number | null) =>
  useQuery({ queryKey: ['escalations', 'one', id], queryFn: () => api<EscalationDetail>(`/api/escalations/${id}`), enabled: id !== null })
export const useTeamsLoad = (runId: 'all' | 'current' = 'current') =>
  useQuery({ queryKey: ['teams', 'load', runId], queryFn: () => api<TeamLoad[]>('/api/teams/load', { query: { run_id: runId } }), refetchInterval: 8_000 })

function invalidateTicketing(qc: ReturnType<typeof useQueryClient>) {
  for (const k of ['tickets', 'escalations', 'incidents', 'notifications', 'metrics', 'teams']) void qc.invalidateQueries({ queryKey: [k] })
}
export function useIncidentAction(id: number | null) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: IncidentAction) => post<IncidentDetail>(`/api/incidents/${id}/actions`, body),
    onSuccess: () => invalidateTicketing(qc),
  })
}
export function useCreateEscalation() {
  const qc = useQueryClient()
  return useMutation({ mutationFn: (body: EscalationCreate) => post<Escalation>('/api/escalations', body), onSuccess: () => invalidateTicketing(qc) })
}
export function useAckEscalation() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...body }: EscalationAck & { id: number }) => post<Escalation>(`/api/escalations/${id}/ack`, body),
    onSuccess: () => invalidateTicketing(qc),
  })
}

// ---- T-009/T-010: мастер настройки и настройки стенда ----
export const useSetupStatus = () => useQuery({ queryKey: ['setup', 'status'], queryFn: () => api<SetupStatus>('/api/setup/status') })
export const useSetupPayload = () => useQuery({ queryKey: ['setup', 'payload'], queryFn: () => api<SetupPayload>('/api/setup') })
export function useSaveSetup() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: Partial<SetupPayload>) => put<SetupPayload>('/api/setup', body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['setup'] })
      void qc.invalidateQueries({ queryKey: ['settings'] })
      void qc.invalidateQueries({ queryKey: ['sim'] })
    },
  })
}
export function useFinishSetup() {
  const qc = useQueryClient()
  return useMutation({ mutationFn: () => post<void>('/api/setup', {}), onSuccess: () => void qc.invalidateQueries({ queryKey: ['setup'] }) })
}
export const useTestLlm = () => useMutation({ mutationFn: (body: TestLlmBody) => post<TestLlmResult>('/api/setup/test-llm', body) })
export const useTestTgBot = () => useMutation({ mutationFn: (token: string) => post<{ ok: boolean; username?: string; error?: string }>('/api/setup/test-tgbot', { token }) })
export const useGenerateStatus = (poll: boolean) =>
  useQuery({ queryKey: ['setup', 'generate'], queryFn: () => api<GenerateStatus>('/api/setup/generate'), refetchInterval: poll ? 1_000 : false })
export function useStartGenerate() {
  const qc = useQueryClient()
  return useMutation({ mutationFn: (body: GenerateBody) => post<{ job_id: string }>('/api/setup/generate', body), onSuccess: () => void qc.invalidateQueries({ queryKey: ['setup'] }) })
}

function settingsQuery<T>(name: string, path: string) {
  return () => useQuery({ queryKey: ['settings', name], queryFn: () => api<T>(path) })
}
export const useSlaMatrix = settingsQuery<SlaCell[]>('sla', '/api/settings/sla-matrix')
export const useRoutingRules = settingsQuery<RoutingRule[]>('routing', '/api/settings/routing-rules')
export const useLlmProfiles = settingsQuery<LlmProfileT[]>('llm-profiles', '/api/settings/llm-profiles')
export const useLlmKeys = settingsQuery<LlmApiKey[]>('llm-keys', '/api/settings/llm-keys')
export const useTemplates = settingsQuery<NotificationTemplateT[]>('templates', '/api/settings/templates')
export const useGifts = settingsQuery<GiftCatalogItem[]>('gifts', '/api/settings/gifts')
export const useEconomicsSettings = settingsQuery<EconomicsSettingsT>('economics', '/api/settings/economics')
export const usePsychotypes = settingsQuery<PsychotypeSettings>('psychotypes', '/api/settings/psychotypes')

export function useSaveSetting<T>(name: string, path: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: T) => put<void>(path, body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['settings', name] })
      void qc.invalidateQueries({ queryKey: ['metrics'] })
    },
  })
}
export function useLlmKeyOps() {
  const qc = useQueryClient()
  const inv = () => void qc.invalidateQueries({ queryKey: ['settings', 'llm-keys'] })
  const add = useMutation({ mutationFn: (b: { provider: string; label: string; key: string }) => post<LlmApiKey>('/api/settings/llm-keys', b), onSuccess: inv })
  const remove = useMutation({ mutationFn: (id: number) => del<void>(`/api/settings/llm-keys/${id}`), onSuccess: inv })
  return { add, remove }
}
export function useLlmProfileOps() {
  const qc = useQueryClient()
  const inv = () => void qc.invalidateQueries({ queryKey: ['settings', 'llm-profiles'] })
  const add = useMutation({ mutationFn: (b: LlmProfileT) => post<void>('/api/settings/llm-profiles', b), onSuccess: inv })
  const save = useMutation({ mutationFn: ({ id, ...b }: LlmProfileT & { id: number }) => patch<void>(`/api/settings/llm-profiles/${id}`, b), onSuccess: inv })
  const remove = useMutation({ mutationFn: (id: number) => del<void>(`/api/settings/llm-profiles/${id}`), onSuccess: inv })
  return { add, save, remove }
}
export function useImportSettings() {
  const qc = useQueryClient()
  return useMutation({ mutationFn: (body: unknown) => post<void>('/api/settings/import', body), onSuccess: () => void qc.invalidateQueries({ queryKey: ['settings'] }) })
}

export const useTasks = (query: Query) =>
  useQuery({ queryKey: ['tasks', query], queryFn: () => api<TaskList>('/api/tasks', { query }), refetchInterval: 10_000 })
export function useTaskDecision() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, action, payload, comment }: { id: number; action: 'approve' | 'change' | 'reject' | 'done'; payload?: Record<string, unknown>; comment?: string }) =>
      post<TaskItem>(`/api/tasks/${id}`, { action, payload, comment }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['tasks'] })
      void qc.invalidateQueries({ queryKey: ['notifications'] })
      void qc.invalidateQueries({ queryKey: ['incidents'] })
    },
  })
}

export const useEnv = () => useQuery({ queryKey: ['settings', 'env'], queryFn: () => api<EnvState>('/api/settings/env') })
export function useSaveEnv() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: EnvUpdate) => put<EnvResult>('/api/settings/env', body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['settings', 'env'] })
      void qc.invalidateQueries({ queryKey: ['health'] })
    },
  })
}

export const useComplianceBranches = () => useQuery({ queryKey: ['compliance', 'branches'], queryFn: () => api<Branch[]>('/api/compliance/branches'), staleTime: 60_000 })
export const useSttProviders = () => useQuery({ queryKey: ['stt', 'providers'], queryFn: () => api<SttProvider[]>('/api/stt/providers'), staleTime: 30_000 })
export const useSttTest = () =>
  useMutation({
    mutationFn: (provider: string) => post<{ ok: boolean; provider: string; text?: string | null; expected?: string; wer?: number | null; latency_ms?: number | null; note_ru?: string }>('/api/stt/test', { provider }),
  })
export function useStartMicSession() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { employee_id: number; client_id?: number | null; deal_product?: string | null; stt_provider?: string; diarization_mode: 'stereo' | 'manual' | 'auto' }) =>
      post<MicSession>('/api/compliance/sessions', { ...body, source: 'mic' }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['compliance'] }),
  })
}

// ---- T-195: меню демонстратора
export const useDemoStatus = () => useQuery({ queryKey: ['demo-status'], queryFn: () => api<DemoStatus>('/api/demo/status') })

export function useDemoFailover() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: DemoFailoverBody) => post<DemoStatus>('/api/demo/failover', body),
    onSuccess: (s) => qc.setQueryData(['demo-status'], s),
  })
}

export function useDemoPlay() {
  return useMutation({
    mutationFn: ({ scenario_id, ...body }: DemoPlayBody & { scenario_id: string }) =>
      post<DemoPlayResult>(`/api/demo/play/${scenario_id}`, body),
  })
}

export const useBenchDatasets = () =>
  useQuery({ queryKey: ['bench', 'datasets'], queryFn: () => api<BenchDatasets>('/api/bench/datasets') })

/** Пока есть queued/running или идёт мутация старта — опрос раз в секунду. */
export function useBenchRuns(starting: boolean) {
  return useQuery({
    queryKey: ['bench', 'runs'],
    queryFn: () => api<BenchRun[]>('/api/bench/runs'),
    refetchInterval: (query) => {
      const rows = query.state.data ?? []
      const live = rows.some((row) => row.status === 'queued' || row.status === 'running')
      return live || starting ? 1000 : false
    },
  })
}

export function useBenchRun(id: number | null) {
  return useQuery({
    queryKey: ['bench', 'run', id],
    queryFn: () => api<BenchRunDetail>(`/api/bench/runs/${id}`),
    enabled: id != null,
  })
}

export const useBenchSentiment = () =>
  useQuery({ queryKey: ['bench', 'sentiment'], queryFn: () => api<SentimentBenchReport>('/api/bench/sentiment') })

export function useBenchDryRun() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: BenchRunCreate) => post<BenchRunAccepted>('/api/bench/runs', { ...body, dry_run: true }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['bench'] }),
  })
}

export function useBenchStart() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: BenchRunCreate) => post<BenchRunAccepted>('/api/bench/runs', { ...body, dry_run: false }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['bench'] }),
  })
}

export function useBenchCancel() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => del<void>(`/api/bench/runs/${id}`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['bench'] }),
  })
}

export function useBaselineRestore() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api<{ job_id?: string }>('/api/sim/baseline/restore', { method: 'POST' }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['sim-state'] })
      void qc.invalidateQueries({ queryKey: ['sim-runs'] })
    },
  })
}
