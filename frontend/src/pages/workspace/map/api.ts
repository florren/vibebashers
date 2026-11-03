import { api, type Schemas } from '@/shared/api/client'
import type { paths } from '@/shared/api/types'
import { requireRunScope } from '@/shared/api/runScope'
import type { CsiHeaders } from '@/pages/csi/api'

export type BranchScope = Omit<NonNullable<paths['/api/branches/analytics']['get']['parameters']['query']>, 'limit' | 'offset' | 'run_id'> & { run_id: string }
export type BranchAnalytics = Schemas['BranchAnalyticsResponse']
export type BranchDetail = Schemas['BranchDetailResponse']
export type ClosedSnapshot = { detail: BranchDetail | null; error: unknown | null }

function detailQuery(scope: BranchScope) {
  return { run_id: requireRunScope(scope.run_id), period: scope.period, product_line: scope.product_line }
}

export function directSignalCount(snapshot: ClosedSnapshot | undefined): number | null {
  return snapshot?.detail && snapshot.error == null && snapshot.detail.scope.run_ids?.length !== 0 ? snapshot.detail.signals.total : null
}

export function branchDetailOptions(code: string | null, scope: BranchScope, headers: CsiHeaders) {
  return {
    queryKey: ['map', 'branches', 'detail', code, scope, headers],
    queryFn: ({ signal }: { signal: AbortSignal }) => api<BranchDetail>(`/api/branches/${encodeURIComponent(code ?? '')}`, { query: detailQuery(scope), headers, signal }),
    staleTime: 15_000, retry: false, enabled: code != null,
  }
}
export function branchAnalyticsOptions(scope: BranchScope, headers: CsiHeaders, offset: number) {
  return {
    queryKey: ['map', 'branches', 'analytics', scope, headers, offset],
    queryFn: ({ signal }: { signal: AbortSignal }) => api<BranchAnalytics>('/api/branches/analytics', { query: { ...scope, run_id: requireRunScope(scope.run_id), limit: 50, offset }, headers, signal }),
    staleTime: 15_000, retry: false,
  }
}

/** Не подменяем direct linkage географической зоной. Неуспешный read остаётся unknown.
 * Три параллельных background reads + один выбранный detail: максимум4 detail requests.
 */
export function closedDetailsOptions(codes: string[], scope: BranchScope, headers: CsiHeaders) {
  return {
    queryKey: ['map', 'branches', 'closed', codes, scope, headers],
    queryFn: async ({ signal }: { signal: AbortSignal }) => {
      const result: Record<string, ClosedSnapshot> = {}
      for (let offset = 0; offset < codes.length; offset += 3) {
        if (signal.aborted) throw signal.reason
        const batch = codes.slice(offset, offset + 3)
        const values = await Promise.allSettled(batch.map(code => api<BranchDetail>(`/api/branches/${encodeURIComponent(code)}`, { query: detailQuery(scope), headers, signal })))
        values.forEach((value, index) => { result[batch[index]!] = value.status === 'fulfilled' ? { detail: value.value, error: null } : { detail: null, error: value.reason } })
      }
      if (signal.aborted) throw signal.reason
      return result
    },
    staleTime: 15_000, retry: false, enabled: codes.length > 0,
  }
}
