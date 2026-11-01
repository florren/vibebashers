import { useQuery } from '@tanstack/react-query'
import { api, type Schemas } from '@/shared/api/client'
import { useSimState } from '@/shared/api/hooks'
import { useWs } from '@/shared/ws/client'

export type Client360 = Schemas['Client360']
export function client360Query(id: number, runId = 'current', hours = 72, currentRunId: number | null = null) {
  return {
    queryKey: ['client360', id, runId, hours, runId === 'current' ? currentRunId : null],
    queryFn: () => api<Client360>(`/api/clients/${id}/360`, { query: { run_id: runId, ops_hours: hours } }),
    staleTime: 30_000,
    gcTime: 5 * 60_000,
  }
}
export function useClient360Clock() {
  const sim = useSimState()
  const live = useWs(state => state.sim)
  return { runId: live?.current_run_id ?? sim.data?.current_run_id ?? null, ready: live != null || sim.isFetched }
}
export function useClient360(id: number | null, runId: string, hours: number) {
  const current = useClient360Clock()
  return useQuery({ ...client360Query(id ?? 0, runId, hours, current.runId), enabled: id != null && (runId !== 'current' || current.ready), refetchInterval: 15_000 })
}
