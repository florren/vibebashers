import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import i18n from '@/shared/i18n'
import { CabinetCalculator } from '../CabinetCalculator'
import { overview } from './fixtures'

vi.mock('@/shared/api/hooks', () => ({ useEconomicsSettings: () => ({ data: { detractor_share: .1, no_return_share: .5, rates: [{ code: 'deposit', name_ru: 'Вклады', name_en: 'Deposits', rate_rub: 961 }, { code: 'credit_card', name_ru: 'Кредитные карты', name_en: 'Credit cards', rate_rub: 305 }] }, isPending: false, isError: false }) }))
beforeEach(async () => { await i18n.changeLanguage('ru') })
afterEach(cleanup)
it('prefills the actual product rate and distinct region customers without writing or inventing a total', async () => {
  const { container, rerender } = render(<CabinetCalculator line={overview.product_lines[0]} region={undefined} />)
  expect(container.querySelector('[aria-live]')).toHaveTextContent('—')
  expect(screen.getByLabelText('Ставка dCLTV')).toHaveValue('deposit')
  rerender(<CabinetCalculator line={overview.product_lines[0]} region={overview.regions[0]} />)
  await waitFor(() => expect(screen.getByLabelText('Пострадавшие')).toHaveValue(2))
  expect(container.querySelector('[aria-live]')).toHaveTextContent(/^−96,1\s₽$/)
  expect(screen.getByText('2 × 0.1 × 0.5 × 961 ₽')).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Пострадавшие'), { target: { value: '20' } })
  expect(container.querySelector('[aria-live]')).toHaveTextContent('961')
  fireEvent.change(screen.getByLabelText('Пострадавшие'), { target: { value: '-1' } })
  expect(container.querySelector('[aria-live]')).toHaveTextContent('—')
})
it('reselects the product-specific rate when direction changes, using the catalog rather than product-code guessing', () => {
  const { rerender } = render(<CabinetCalculator line={overview.product_lines[0]} region={undefined} />)
  rerender(<CabinetCalculator line={{ ...overview.product_lines[0]!, code: 'credit_cards', rate_code: 'credit_card' }} region={undefined} />)
  expect(screen.getByLabelText('Ставка dCLTV')).toHaveValue('credit_card')
})
