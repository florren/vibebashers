import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import i18n from '@/shared/i18n'
import { CabinetChart } from '../CabinetChart'
import { overview } from './fixtures'

const chart = vi.hoisted(() => ({ setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn() }))
const initialize = vi.hoisted(() => vi.fn())
vi.mock('echarts', () => ({ init: initialize }))
beforeEach(async () => {
  await i18n.changeLanguage('en'); initialize.mockReset().mockReturnValue(chart); chart.setOption.mockReset(); chart.dispose.mockReset()
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} })
})
afterEach(() => { cleanup(); vi.unstubAllGlobals() })
it('uses SVG, disables animation, preserves missing money and offers a data table', () => {
  const { unmount } = render(<CabinetChart data={overview} />)
  expect(initialize).toHaveBeenCalledWith(expect.any(HTMLElement), undefined, { renderer: 'svg' })
  const option = chart.setOption.mock.calls.at(-1)![0]
  expect(option.animation).toBe(false)
  expect(option.series[0].data).toEqual([null])
  expect(option.series[0].connectNulls).toBe(false)
  fireEvent.click(screen.getByText('Show chart data as a table'))
  expect(screen.getByRole('table')).toHaveTextContent('2026-11-09')
  expect(screen.getByRole('table')).toHaveTextContent('—')
  unmount(); expect(chart.dispose).toHaveBeenCalled()
})
it('marks synthetic history and shows safe platform names with an unknown bucket', () => {
  const { container } = render(<CabinetChart data={overview} />)
  fireEvent.click(screen.getByText('12 months'))
  expect(screen.getByText(/Historical aggregates are synthetic/)).toBeInTheDocument()
  expect(screen.getByRole('table')).toHaveTextContent('Synthetic aggregates')
  fireEvent.click(screen.getByText('Source platforms'))
  expect(screen.getByRole('table')).toHaveTextContent('Customer reviews')
  expect(screen.getByRole('table')).toHaveTextContent('Unknown platform')
  expect(container.querySelector('a,img')).toBeNull()
  expect(chart.setOption.mock.calls.at(-1)![0].xAxis.data).toEqual(['Customer reviews', 'Unknown platform'])
})
