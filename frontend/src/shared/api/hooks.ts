import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  api,
  ApiError,
  post,
  type AgentGraph,
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
  useQuery({ queryKey: ['hitl', 'queue', query], queryFn: () => api<List<HitlItem>>('/api/hitl/queue', { query }), placeholderData: (p) => p })
export const useHitlItem = (id: number | null) =>
  useQuery({ queryKey: ['hitl', 'one', id], queryFn: () => api<HitlItem>(`/api/hitl/${id}`), enabled: id !== null })
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
