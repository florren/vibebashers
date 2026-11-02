import { expect, it } from 'vitest'
import { explicitPreviewInput } from '../previewInput'

const settings = { fallback_rate_code: 'bank_average', detractor_share: 0, no_return_share: 0, rates: [{ code: 'deposit', name_ru: 'Вклады', rate_rub: 961 }] }
it('preserves explicit known zero values without API defaults', () => {
  expect(explicitPreviewInput(0, 'deposit', settings)).toEqual({ affected: 0, rate_code: 'deposit', detractor_share: 0, no_return_share: 0 })
})
it('requires known cohort, actual rate and both coefficients', () => {
  expect(explicitPreviewInput(null, 'deposit', settings)).toBeNull()
  expect(explicitPreviewInput(2, 'missing', settings)).toBeNull()
  expect(explicitPreviewInput(2, 'deposit', undefined)).toBeNull()
  expect(explicitPreviewInput(2, 'deposit', { ...settings, detractor_share: undefined })).toBeNull()
  expect(explicitPreviewInput(NaN, 'deposit', settings)).toBeNull()
})
