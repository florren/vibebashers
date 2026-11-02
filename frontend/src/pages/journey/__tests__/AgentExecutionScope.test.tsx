import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { expect, it, vi } from 'vitest'
import '@/shared/i18n'
import { AgentExecution } from '../AgentExecution'
vi.mock('@/pages/engine/GraphView', () => ({ GraphView: () => <div /> }))
vi.mock('@/pages/workspace/HitlQueue', () => ({ HitlCard: () => <button>human-accept-fixture</button> }))
vi.mock('@/shared/api/hooks', () => ({
  useAgentGraph: () => ({ data: { version: 'test', nodes: [], edges: [] } }),
  useHitlItem: () => ({ data: { id: 4 } }),
  useRefName: () => (code: string) => code,
}))
it('keeps legacy HITL controls but excludes them from an explicit readonly context', () => {
  const props = { events: [], selection: null, onSelectStep: vi.fn(), onFollowCurrent: vi.fn(), onOpenSignal: vi.fn(), current: 'wait_human', run: { id: 10, outcome: 'awaiting_human' as const, human_decision: { id: 4 }, steps: [] } }
  const view = render(<MemoryRouter><AgentExecution {...props} /></MemoryRouter>)
  expect(screen.getByText('human-accept-fixture')).toBeInTheDocument()
  view.rerender(<MemoryRouter><AgentExecution {...props} readOnly /></MemoryRouter>)
  expect(screen.queryByText('human-accept-fixture')).not.toBeInTheDocument()
  expect(screen.getByText(/Контекст выбранного запуска: только просмотр/)).toBeInTheDocument()
})
