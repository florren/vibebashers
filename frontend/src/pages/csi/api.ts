import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { requireRunScope } from '@/shared/api/runScope'
import { api, type Query, type Schemas } from '@/shared/api/client'

export type CsiAnalytics = Schemas['CsiAnalyticsResponse']
export type CsiScope = { run_id: string; period: 'day' | 'week' | 'month' | 'quarter'; product_line?: string; region_code?: string; branch_id?: number; offset: number }
export type CsiHeaders = { 'X-Cx-Role': string; 'X-Cx-Product-Line'?: string }

export function analyticsOptions(scope: CsiScope, headers: CsiHeaders) {
  return {
    queryKey: ['csi', 'analytics', scope, headers],
    queryFn: ({ signal }: { signal: AbortSignal }) => api<CsiAnalytics>('/api/csi/analytics', { query: { ...scope, run_id: requireRunScope(scope.run_id), limit: 50, scatter_limit: 1000 }, headers, signal }),
    staleTime: 15_000,
    // Старый результат другого role/run/direction не показывается как новый.
    retry: false,
  }
}

export function useBranchDirectory(scope: Pick<CsiScope, 'product_line' | 'region_code'>, headers: CsiHeaders, enabled = true) {
  return useInfiniteQuery({
    enabled,
    queryKey: ['csi', 'directory', scope, headers],
    queryFn: ({ pageParam, signal }) => api<Schemas['BranchDirectoryResponse']>('/api/branches', { query: { ...scope, limit: 200, cursor: pageParam }, headers, signal }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: page => page.next_cursor ?? undefined,
    staleTime: 86_400_000,
    retry: false,
  })
}

export function useDirectionCatalog(headers: CsiHeaders, enabled = true) {
  // Каталог уже входит в согласованный read-only cabinet API. Не подменяем
  // выбранный role ради получения более широкого списка направлений.
  return useQuery({
    enabled,
    queryKey: ['csi', 'directions', headers],
    queryFn: async ({ signal }) => {
      const snapshot = await api<Schemas['CabinetOverview']>('/api/cabinet/overview', { query: { run_id: 'current' } satisfies Query, headers, signal })
      return snapshot.product_lines
    },
    staleTime: 86_400_000,
    retry: false,
  })
}
