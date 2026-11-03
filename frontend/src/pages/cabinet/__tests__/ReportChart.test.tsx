import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import i18n from '@/shared/i18n'
import type { Schemas } from '@/shared/api/client'
import { ReportChart } from '../ReportChart'
import { overview } from './fixtures'

const chart = vi.hoisted(() => ({ setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn() }))
const initialize = vi.hoisted(() => vi.fn())
vi.mock('echarts', () => ({ init: initialize }))
beforeEach(async () => { await i18n.changeLanguage('en'); initialize.mockReset().mockReturnValue(chart); chart.setOption.mockReset(); vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} }) })
afterEach(() => { cleanup(); vi.unstubAllGlobals() })
// Оставшиеся поля report не используются графиком; реальный полный DTO проверен API/PG.
const report = { lang: 'en', overview, charts: [{ code: 'daily', title_insight: 'Saved estimates' }] } as Schemas['CabinetReport']
it('does not invent a zero financial axis for unknown saved money', () => {
  render(<ReportChart report={report} code="daily" />)
  expect(screen.getByText('No saved money calculations for these days')).toBeInTheDocument()
  expect(initialize).not.toHaveBeenCalled()
})
it('shows known monthly counts with a hidden unknown-money axis and hatched bars', () => {
  render(<ReportChart report={report} code="monthly" />)
  const option = chart.setOption.mock.calls.at(-1)![0]
  expect(option.yAxis[0].show).toBe(false)
  expect(option.series).toHaveLength(1)
  expect(option.series[0].type).toBe('bar')
  expect(option.series[0].itemStyle.decal).toBeTruthy()
  expect(option.series[0].data).toEqual([10])
})
it('uses short axis labels for large geometry while keeping SVG markers, gaps and disabled animation', () => {
  const data = { ...report, overview: { ...overview, daily: [{ ...overview.daily[0]!, potential_loss_rub: 400_000_000_000_000, prevented_loss_rub: 1 }, { ...overview.daily[0]!, day: '2026-11-08' }] } }
  render(<ReportChart report={data} code="daily" />)
  const option = chart.setOption.mock.calls.at(-1)![0]
  expect(initialize).toHaveBeenCalledWith(expect.any(HTMLElement), undefined, { renderer: 'svg' })
  expect(option.yAxis[0].axisLabel.formatter(400_000_000_000_000).length).toBeLessThan(12)
  expect(option.series[0].data).toEqual([400_000_000_000_000, null])
  expect(option.series[0].symbol).toBe('triangle')
  expect(option.series[1].lineStyle.type).toBe('dashed')
  expect(option.series[0].connectNulls).toBe(false)
  expect(option.animation).toBe(false)
})
