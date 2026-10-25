import type { ReactNode } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('echarts', () => ({
  init: vi.fn(() => ({ setOption: vi.fn(), dispose: vi.fn(), resize: vi.fn() })),
}))

import i18n from '@/shared/i18n'
import { BenchTab } from '@/pages/engine/BenchTab'

const SEVEN = ['gigachat_ultra', 'gigachat_lightning', 'gigachat_pro', 'or_nemotron_ultra', 'or_owl_alpha', 'or_gpt_oss_120b', 'mock'] as const

const SHORTAGE = 'квота исчерпана'
const QUIET = 'близко к суточному лимиту'

type Mode = 'ok' | 'shortage' | 'quiet'

let mode: Mode = 'ok'

function profile(id: number, code: string, provider: 'gigachat' | 'openai_compatible' | 'mock', apiKey: number | null, rpm: number | null, rpd: number | null) {
  return { id, code, provider, model: code, role: 'bench_only' as const, is_active: true, rpm_limit: rpm, rpd_limit: rpd, api_key_id: apiKey }
}

const profiles = [
  profile(8, 'local_openai', 'openai_compatible', 2, 5, 100),
  profile(7, 'mock', 'mock', null, null, null),
  profile(3, 'gigachat_pro', 'gigachat', 1, null, null),
  profile(1, 'gigachat_ultra', 'gigachat', 1, null, null),
  profile(6, 'or_gpt_oss_120b', 'openai_compatible', 2, 18, 1000),
  profile(2, 'gigachat_lightning', 'gigachat', 1, null, null),
  profile(4, 'or_nemotron_ultra', 'openai_compatible', 2, 18, 1000),
  profile(5, 'or_owl_alpha', 'openai_compatible', 2, 18, 1000),
]

function accuracy(code: string): number {
  if (code === 'gigachat_lightning') return 0.95
  if (code === 'gigachat_ultra') return 0.2
  return 0.5
}

const runs = profiles.map((item) => ({
  id: 100 + item.id,
  dataset_code: 'lite',
  llm_profile_code: item.code,
  prompt_version: 'v1',
  status: 'done',
  repeats: 1,
  progress: 1,
  metrics: {
    accuracy_type: accuracy(item.code),
    accuracy_product: 0.5,
    accuracy_system: 0.5,
    accuracy_criticality: 0.5,
    accuracy_route: 0.5,
    recall_critical: 0.5,
    json_valid_rate: 1,
    tool_success_rate: 1,
    retries_avg: 0.1,
    fallback_rate: 0,
    p50_ms: 120,
    p95_ms: 400,
    tokens_total: 30,
    cost_estimate: 0,
    stability: 1,
  },
}))

const keys = [
  { id: 1, provider: 'gigachat', label: 'gc', tokens_used: 12, tokens_limit: 100, requests_today: 1, rpd_limit: 50, balance_usd: null, is_active: true },
  { id: 2, provider: 'openai_compatible', label: 'or', tokens_used: 0, tokens_limit: null, requests_today: 4, rpd_limit: 1000, balance_usd: 47, is_active: true },
]

function jsonRes(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })
}

function forecastBody() {
  if (mode === 'shortage') return { run_ids: [], forecast: [{ llm_profile_id: 1, est_tokens: 100, est_requests: 10, fits_limits: false, warning: SHORTAGE }] }
  if (mode === 'quiet') return { run_ids: [], forecast: [{ llm_profile_id: 1, est_tokens: 10, est_requests: 1, fits_limits: true, warning: QUIET }] }
  return { run_ids: [], forecast: [{ llm_profile_id: 1, est_tokens: 10, est_requests: 1, fits_limits: true, warning: '' }] }
}

function wrap(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
}

function headers(): string[] {
  return screen.getAllByRole('columnheader').map((el) => el.textContent?.trim() ?? '')
}

describe('BenchTab', () => {
  beforeEach(() => {
    mode = 'ok'
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      if (url.includes('/api/settings/llm-profiles')) return jsonRes(profiles)
      if (url.includes('/api/settings/llm-keys')) return jsonRes(keys)
      if (url.includes('/api/bench/datasets')) return jsonRes([{ id: 1, code: 'lite', title_ru: 'Lite', cases: 10 }])
      if (url.includes('/api/bench/sentiment')) return jsonRes({ dataset: 'sentiment_v1', size: 1, providers: [{ provider: 'mock', model: 'mock', accuracy: 0.9, passed: true, confusion: { negative: { negative: 1 } } }] })
      if (/\/api\/bench\/runs\/\d+/.test(url)) {
        const run = runs[0]
        return jsonRes({ ...run, results: [{ case_id: 1, text: 'текст', gold: { type: 'fee' }, predicted: { type: 'other' }, correct: { type: false }, json_valid_first_try: true, fallback_mock: false }] })
      }
      if (url.includes('/api/bench/runs') && method === 'POST') return jsonRes(forecastBody(), 202)
      if (url.includes('/api/bench/runs')) return jsonRes(runs)
      return jsonRes({})
    }))
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('ставит колонки семи профилей, local_openai после mock и выключен в запуске', async () => {
    render(wrap(<BenchTab />))
    await screen.findByRole('columnheader', { name: 'gigachat_ultra' })
    expect(headers().slice(1, 9)).toEqual([...SEVEN, 'local_openai'])
    expect(screen.getByRole('checkbox', { name: 'gigachat_ultra' })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: 'local_openai' })).not.toBeChecked()
  })

  it('при fits_limits false показывает alert и не даёт старт', async () => {
    mode = 'shortage'
    render(wrap(<BenchTab />))
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(SHORTAGE)
    expect(alert).toHaveTextContent(i18n.t('bench.limitWarning'))
    expect(screen.getByRole('button', { name: i18n.t('bench.start') })).toBeDisabled()
  })

  it('клик по метрике меняет порядок колонок и класс лучшей ячейки', async () => {
    render(wrap(<BenchTab />))
    await screen.findByRole('columnheader', { name: 'gigachat_ultra' })
    expect(headers()[1]).toBe('gigachat_ultra')
    fireEvent.click(screen.getByRole('button', { name: i18n.t('bench.metric.accuracy_type') }))
    expect(headers()[1]).toBe('gigachat_lightning')
    const row = screen.getByRole('button', { name: i18n.t('bench.metric.accuracy_type') }).closest('tr')
    if (!row) throw new Error('нет строки метрики')
    const cells = within(row).getAllByRole('cell')
    const best = cells[0]
    const next = cells[1]
    if (!best || !next) throw new Error('нет ячеек')
    expect(best).toHaveClass('bg-brand-soft')
    expect(best).toHaveTextContent('0.950')
    expect(next).not.toHaveClass('bg-brand-soft')
  })

  it('непустой warning при fits_limits true не становится alert нехватки', async () => {
    mode = 'quiet'
    render(wrap(<BenchTab />))
    expect(await screen.findByText(QUIET)).toBeInTheDocument()
    expect(screen.queryByRole('alert')).toBeNull()
    expect(screen.queryByText(i18n.t('bench.limitWarning'))).toBeNull()
    expect(screen.getByRole('button', { name: i18n.t('bench.start') })).toBeEnabled()
  })
})
