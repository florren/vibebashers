import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  api,
  post,
  type AgentGraph,
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
