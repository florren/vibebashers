import type { Schemas } from '@/shared/api/client'
import type { EconomicsPreviewInput } from '@/shared/api/useEconomicsPreview'

/** Не превращаем отсутствующий cohort/коэффициент/ставку в default API. */
export function explicitPreviewInput(affected: number | null | undefined, rateCode: string | null | undefined, settings: Schemas['EconomicsSettings'] | undefined): EconomicsPreviewInput | null {
  const rate = settings?.rates?.find(row => row.code === rateCode)
  const detractor = settings?.detractor_share, noReturn = settings?.no_return_share
  if (affected == null || !Number.isInteger(affected) || affected < 0 || !rate || detractor == null || noReturn == null || !Number.isFinite(detractor) || !Number.isFinite(noReturn)) return null
  return { affected, rate_code: rate.code, detractor_share: detractor, no_return_share: noReturn }
}
