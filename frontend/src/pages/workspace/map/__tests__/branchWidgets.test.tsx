import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import i18n from '@/shared/i18n'
import { api } from '@/shared/api/client'
import { BranchLayer } from '../BranchLayer'
import { BranchCard } from '../BranchCard'
import { BranchAnalytics } from '../BranchAnalytics'
import { closedBranch, detail, analytics } from './fixtures'

vi.mock('@/shared/api/client', async original => ({ ...await original<typeof import('@/shared/api/client')>(), api: vi.fn() }))
vi.mock('@/pages/csi/Chart', () => ({ CsiChart: ({ label }: { label: string }) => <div role="img" aria-label={label} /> }))
beforeEach(async () => { await i18n.changeLanguage('ru'); vi.mocked(api).mockResolvedValue([{ code: '77', name_ru: 'Москва', name_en: 'Moscow' }]) })
afterEach(cleanup)
const point = { branch: closedBranch, x: 100, y: 150 }
const cluster = { key: closedBranch.code, items: [point], anchor: point }

it('closed count is native direct linkage; missing/error stays unknown and keyboard opens exact native point', () => {
  const select = vi.fn()
  const { rerender } = render(<svg><BranchLayer clusters={[cluster]} pixelRatio={1} zoom={1} closed={undefined} selected={null} onSelect={select} /></svg>)
  expect(screen.getByText('закрыто · число сигналов неизвестно')).toBeVisible()
  fireEvent.keyDown(screen.getByRole('button'), { key: 'Enter' })
  expect(select).toHaveBeenCalledWith(cluster)
  rerender(<svg><BranchLayer clusters={[cluster]} pixelRatio={1} zoom={1} closed={{ [closedBranch.code]: { detail, error: null } }} selected={null} onSelect={select} /></svg>)
  expect(screen.getByText('закрыто · 2 сигнала')).toBeVisible()
  expect(screen.queryByText(/99 сигнал/)).not.toBeInTheDocument()
  rerender(<svg><BranchLayer clusters={[cluster]} pixelRatio={1} zoom={1} closed={{ [closedBranch.code]: { detail: null, error: new Error('unavailable') } }} selected={null} onSelect={select} /></svg>)
  expect(screen.getByText('закрыто · число сигналов неизвестно')).toBeVisible()
})

it('card keeps unknown CSI sample and scoped internal links without external href or invented address', () => {
  const { container } = render(<MemoryRouter><BranchCard data={detail} error={null} loading={false} runId="19" close={vi.fn()} /></MemoryRouter>)
  expect(screen.getByText('Неизвестно / Неизвестно')).toBeVisible()
  expect(container.querySelector('a[href="/trace/branch/42?run_id=19"]')).not.toBeNull()
  expect(container.querySelector('a[href^="http"]')).toBeNull()
})

it('analytics separates city zone99 from direct counts and refuses a guessed deficit threshold', () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><MemoryRouter><BranchAnalytics data={analytics} runId="19" region={null} onRegion={vi.fn()} offset={0} onOffset={vi.fn()} /></MemoryRouter></QueryClientProvider>)
  expect(screen.getByText('Порог дефицита не задан: метрика не определена.')).toBeVisible()
  expect(screen.getByText(/Это не прямая связь с ВСП/)).toBeVisible()
  expect(screen.getByText('99')).toBeVisible()
  expect(screen.getByLabelText('Динамика сети: 12 месяцев')).toBeVisible()
  client.clear()
})


it('cluster count separates from the heat-label baseline without moving the native anchor or touch area', () => {
  const second = { ...point, branch: { ...point.branch, code: 'VSP-0043' } }
  const grouped = { ...cluster, items: [point, second] }
  const select = vi.fn()
  const { container } = render(<svg><BranchLayer clusters={[grouped]} pixelRatio={.5} zoom={4} closed={undefined} selected={null} onSelect={select} /></svg>)
  const marker = screen.getByRole('button')
  expect(marker).toHaveAttribute('transform', 'translate(100 150) scale(0.5)')
  expect(marker).toHaveAttribute('data-branch-codes', 'VSP-0042 VSP-0043')
  expect(container.querySelector('circle')).toHaveAttribute('r', '22')
  expect(container.querySelectorAll('circle')[1]).toHaveAttribute('fill', 'none')
  const count = screen.getByText('2')
  expect(Number(count.getAttribute('y'))).toBeGreaterThan(12)
  fireEvent.keyDown(marker, { key: ' ' })
  expect(select).toHaveBeenCalledWith(grouped)
})

it('decimal code0042 remains visible but both Trace links address the actual primary key', () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const numericDetail = { ...detail, branch: { ...detail.branch, id: 1, code: '0042' }, scope: { ...detail.scope, branch_id: 1 } }
  const numericAnalytics = { ...analytics, closure_zones: { ...analytics.closure_zones, items: [{ ...analytics.closure_zones.items[0]!, branch_id: 1, branch_code: '0042' }] } }
  const { container } = render(<QueryClientProvider client={client}><MemoryRouter><BranchCard data={numericDetail} error={null} loading={false} runId="19" close={vi.fn()} /><BranchAnalytics data={numericAnalytics} runId="19" region={null} onRegion={vi.fn()} offset={0} onOffset={vi.fn()} /></MemoryRouter></QueryClientProvider>)
  expect(screen.getAllByText('0042')).toHaveLength(2)
  expect(container.querySelectorAll('a[href="/trace/branch/1?run_id=19"]')).toHaveLength(2)
  expect(container.querySelector('a[href="/trace/branch/0042?run_id=19"]')).toBeNull()
  expect(container.querySelector('a[href="/trace/branch/42?run_id=19"]')).toBeNull()
  client.clear()
})
