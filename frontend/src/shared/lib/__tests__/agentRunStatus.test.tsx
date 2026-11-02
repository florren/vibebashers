import { MemoryRouter } from 'react-router-dom'
import type { Trace } from '@/shared/api/trace'
import { SubjectCard } from '@/pages/trace/components/SubjectCard'
import { render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import i18n from '@/shared/i18n'
import { GraphView } from '@/pages/engine/GraphView'
import { LogPanel } from '@/widgets/LogPanel'
import { nodeStatus } from '@/pages/journey/stepSelection'
import { agentRunStatus } from '../agentRunStatus'

vi.mock('@/shared/api/hooks', () => ({ useAgentRun: () => ({ isPending: false, isError: false, data: { id: 1, outcome: null, status: 'interrupted', interrupted_at: '2026-11-02T00:00:00Z', needed_human: true, steps: [] } }) }))
vi.mock('@/shared/ws/client', () => ({ useWs: () => 0 }))
afterEach(async () => { await i18n.changeLanguage('ru') })
it('preserves legacy fallback and business outcome without changing the object', () => {
  expect(agentRunStatus(undefined)).toBe('running')
  expect(agentRunStatus({ outcome: 'awaiting_human' })).toBe('awaiting_human')
  expect(agentRunStatus({ outcome: null, interrupted_at: '2026-11-02T00:00:00Z' })).toBe('interrupted')
  expect(agentRunStatus({ outcome: 'completed', interrupted_at: '2026-11-02T00:00:00Z' })).toBe('completed')
  const run = { outcome: null, status: 'interrupted' as const, interrupted_at: '2026-11-02T00:00:00Z', needed_human: true }
  expect(agentRunStatus(run)).toBe('interrupted')
  expect(run.outcome).toBeNull()
  expect(run.needed_human).toBe(true)
  expect(nodeStatus(run, 'decide', 'decide')).toBe('interrupted')
  expect(nodeStatus({ outcome: 'awaiting_human' }, 'decide', 'decide')).toBe('waiting_human')
})
it.each([['ru', 'прерван'], ['en', 'interrupted']])('renders interrupted in %s without presenting an active run', async (lang, text) => {
  await i18n.changeLanguage(lang)
  render(<LogPanel runId={1} full />)
  expect(screen.getByText(text)).toBeInTheDocument()
})
it('shows an interrupted current node statically and keeps the legacy running animation', () => {
  const props = { graph: { nodes: [{ id: 'decide', kind: 'llm' as const }], edges: [] }, visited: new Set<string>(), current: 'decide', outcome: null }
  const { container, rerender } = render(<GraphView {...props} executionStatus="interrupted" />)
  expect(container.querySelector('[data-execution-status="interrupted"]')).not.toBeNull()
  expect(container.querySelector('.animate-pulse')).toBeNull()
  rerender(<GraphView {...props} />)
  expect(container.querySelector('[data-execution-status="running"]')).not.toBeNull()
  expect(container.querySelector('.animate-pulse')).not.toBeNull()
})

it.each([['ru', 'прерван'], ['en', 'interrupted']])('localizes only the agent trace subject in %s', async (lang, text) => {
  await i18n.changeLanguage(lang)
  const trace: Trace = { subject: { kind: 'agent_run', ref: 'AR-42', title_ru: 'AR-42', status: 'interrupted' }, before: [], after: [], edges: [], groups: [], pending: [], terminal: { reached: false }, stats: { before_count: 0, after_count: 0, build_ms: 1 } }
  const { rerender } = render(<MemoryRouter><SubjectCard trace={trace} /></MemoryRouter>)
  expect(screen.getByText(text, { exact: true })).toBeInTheDocument()
  rerender(<MemoryRouter><SubjectCard trace={{ ...trace, subject: { ...trace.subject, kind: 'other', status: 'raw_custom_status' } }} /></MemoryRouter>)
  expect(screen.getByText('raw_custom_status')).toBeInTheDocument()
})
