import type { AgentRunBrief } from '@/shared/api/client'

/** Presentation only: бизнес-исход и HITL conditions остаются в outcome. */
export function agentRunStatus(run: Pick<AgentRunBrief, 'status' | 'outcome' | 'interrupted_at'> | undefined): string {
  return run?.status ?? (run?.outcome == null && run?.interrupted_at ? 'interrupted' : run?.outcome ?? 'running')
}
