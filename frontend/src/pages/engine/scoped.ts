import { api, ApiError, type Schemas } from '@/shared/api/client'

/** Полный keyset walk: отсутствие ID на первой странице не означает foreign run. */
export async function scopedAgentMembership(id: number, run: string, signal?: AbortSignal): Promise<boolean> {
  let cursor: string | undefined
  const seen = new Set<string>()
  for (;;) {
    const page = await api<Schemas['AgentRunList']>('/api/agent/runs', {
      query: { run_id: run, q: `AR-${id}`, kind: 'agent', limit: 100, cursor }, signal,
    })
    if (page.items?.some(item => item.id === id)) return true
    if (!page.next_cursor) return false
    if (seen.has(page.next_cursor)) throw new ApiError(502, { title: 'Invalid agent pagination cursor' }, 'Invalid pagination')
    seen.add(page.next_cursor)
    cursor = page.next_cursor
  }
}
