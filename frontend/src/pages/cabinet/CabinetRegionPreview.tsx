import { useTranslation } from 'react-i18next'
import { useEconomicsSettings } from '@/shared/api/hooks'
import { useEconomicsPreview } from '@/shared/api/useEconomicsPreview'
import { ErrorBox } from '@/shared/ui'
import type { Overview } from './api'
import { explicitPreviewInput } from './previewInput'
import { compactMoney } from './format'

/** Региональная карточка читает тот же pure server preview, не materialized экономику. */
export function CabinetRegionPreview({ line, region, scopeKey }: { line: Overview['product_lines'][number] | undefined; region: Overview['regions'][number]; scopeKey: string }) {
  const { t, i18n } = useTranslation(), settings = useEconomicsSettings()
  const rateCode = line ? line.rate_code ?? settings.data?.fallback_rate_code : null
  const input = explicitPreviewInput(region.affected_clients, rateCode, settings.data)
  const result = useEconomicsPreview(input, JSON.stringify([scopeKey, settings.dataUpdatedAt]))
  const total = input === null || result.isError || settings.isError ? null : result.data?.potential_loss_rub
  return <div className="space-y-1 text-sm" data-testid="region-loss-preview">
    <p>{t('cabinet.scenarioLoss')}: <span className="num">{total == null ? '—' : compactMoney(total > 0 ? -total : total, i18n.language)}</span></p>
    {input === null && <p className="text-muted">{t('cabinet.regionEstimateUnknown')}</p>}
    {result.isFetching && <p role="status">{t('cabinet.calculating')}</p>}
    {(result.isError || settings.isError) && <ErrorBox error={result.error ?? settings.error} />}
    <p className="text-muted">{t('cabinet.calculatorHint')}</p>
  </div>
}
