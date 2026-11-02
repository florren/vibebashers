import { useQuery } from '@tanstack/react-query'
import { api, type Schemas } from '@/shared/api/client'
import { projectSignal } from './model'

export { useMetricsOverview as useOverview } from '@/shared/api/overview'
export const useCxIndex = (run: string | null) => useQuery({ queryKey: ['metrics', 'cx-index', run], queryFn: ({ signal }) => api<Schemas['CxIndex']>('/api/metrics/cx-index', { query: { run_id: run }, signal }), enabled: run !== null, refetchInterval: 8000 })
export const useOverviewSignals = (run: string | null, since: string | undefined, night = false) => useQuery({ queryKey: ['signals', 'overview', run, since, night], queryFn: async ({ signal }) => {
  const data = await api<Schemas['SignalList']>('/api/signals', { query: { run_id: run, since_sim: since, limit: night ? 10 : 40, criticality: night ? 'high' : undefined }, signal })
  return { items: data.items?.map(projectSignal) ?? [], more: Boolean(data.next_cursor), limit: night ? 10 : 40 }
}, enabled: run !== null && Boolean(since), refetchInterval: 8000 })
