import { useEffect } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api, type Schemas } from '@/shared/api/client'
import type { paths } from '@/shared/api/types'
import { useWs } from '@/shared/ws/client'

export type Overview = Schemas['CabinetOverview']
export type CabinetSignal = Schemas['CabinetSignal']
export type CabinetScope = NonNullable<paths['/api/cabinet/overview']['get']['parameters']['query']>
type GeneratedFilters = NonNullable<paths['/api/cabinet/signals']['get']['parameters']['query']>
// URL — недоверенная граница: сохраняем raw bool text для серверной422-валидации.
export type SignalFilters = Omit<GeneratedFilters, 'red_words'> & { red_words?: GeneratedFilters['red_words'] | string }
export type CabinetHeaders = NonNullable<paths['/api/cabinet/overview']['get']['parameters']['header']>

export function useCabinetOverview(scope: CabinetScope, headers: CabinetHeaders) {
  return useQuery({ queryKey: ['cabinet', 'overview', scope, headers], queryFn: ({ signal }) => api<Overview>('/api/cabinet/overview', { query: scope, headers, signal }), staleTime: 15_000, refetchInterval: 30_000 })
}
export function signalsOptions(filters: SignalFilters, headers: CabinetHeaders) {
  return { queryKey: ['cabinet', 'signals', filters, headers], queryFn: ({ signal }: { signal: AbortSignal }) => api<Schemas['CabinetSignals']>('/api/cabinet/signals', { query: filters, headers, signal }), staleTime: 15_000 }
}
export function useCabinetEvents() {
  const cache = useQueryClient()
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined
    const stop = useWs.subscribe((state, previous) => {
      if (state.events === previous.events || !['signals', 'incidents', 'runs', 'compliance', 'metrics'].includes(state.events[0]?.topic ?? '')) return
      if (!timer) timer = setTimeout(() => { timer = undefined; void cache.invalidateQueries({ queryKey: ['cabinet'] }) }, 500)
    })
    return () => { stop(); clearTimeout(timer) }
  }, [cache])
}
