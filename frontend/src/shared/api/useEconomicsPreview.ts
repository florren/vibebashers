import { useQuery } from '@tanstack/react-query'
import { api, type Schemas } from './client'
import type { paths } from './types'

export type EconomicsPreviewInput = NonNullable<paths['/api/metrics/economics/preview']['get']['parameters']['query']>

/** Scope нужен кешу UI; HTTP preview принимает только явные сценарные входы, не incident/run. */
export function useEconomicsPreview(input: EconomicsPreviewInput | null, scopeKey: string) {
  return useQuery({
    queryKey: ['economics-preview', 'explicit', scopeKey, input],
    enabled: input !== null,
    queryFn: ({ signal }) => {
      if (input === null) throw new Error('Нет явных входных данных для расчёта')
      return api<Schemas['IncidentEconomics']>('/api/metrics/economics/preview', { query: input, signal })
    },
  })
}
