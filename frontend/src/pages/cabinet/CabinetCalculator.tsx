import { compactMoney } from './format'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useEconomicsSettings } from '@/shared/api/hooks'
import { useEconomicsPreview } from '@/shared/api/useEconomicsPreview'
import { explicitPreviewInput } from './previewInput'
import { ErrorBox, Skeleton } from '@/shared/ui'
import type { Overview } from './api'

/** Только сценарные допущения из действующих settings/rates; никаких финансовых записей. */
export function CabinetCalculator({ line, region, scopeKey }: { line: Overview['product_lines'][number] | undefined; region: Overview['regions'][number] | undefined; scopeKey: string }) {
  const { t, i18n } = useTranslation()
  const settings = useEconomicsSettings()
  const [affected, setAffected] = useState<number | null>(null)
  const [rateCode, setRateCode] = useState<string | null>(null)
  const lineCode = line?.code
  const defaultRate = lineCode ? line?.rate_code ?? settings.data?.fallback_rate_code ?? null : null
  // Новый scope сбрасывает ручной выбор даже при одинаковой fallback ставке.
  useEffect(() => setRateCode(defaultRate), [lineCode, defaultRate])
  useEffect(() => { setAffected(region?.affected_clients ?? null) }, [region?.code, region?.affected_clients])
  const rates = settings.data?.rates ?? []
  const input = explicitPreviewInput(affected, rateCode, settings.data)
  const result = useEconomicsPreview(input, JSON.stringify([scopeKey, settings.dataUpdatedAt]))
  const data = input === null || result.isError || settings.isError ? undefined : result.data
  const total = data?.potential_loss_rub
  const actualNumber = (value: number | null | undefined) => value == null ? '—' : new Intl.NumberFormat(i18n.language, { maximumFractionDigits: 2 }).format(value)
  return <div className="space-y-3">
    <p className="text-sm text-muted">{t('cabinet.calculatorHint')}</p>
    {settings.isError ? <ErrorBox error={settings.error} /> : settings.isPending ? <Skeleton className="h-20" /> : <>
      <label className="block text-sm">{t('cabinet.rate')}<select className="input mt-1 w-full" value={rateCode ?? ''} onChange={e => setRateCode(e.target.value || null)}><option value="">{t('cabinet.chooseRate')}</option>{rates.map(row => <option key={row.code} value={row.code}>{i18n.language.startsWith('en') ? row.name_en : row.name_ru} · {compactMoney(row.rate_rub, i18n.language)}</option>)}</select></label>
      <label className="block text-sm">{t('incidentEconomics.affected')}<input className="input mt-1 w-full" type="number" min={0} max={100000000} step={1} value={affected ?? ''} onChange={e => { const value = Number(e.target.value); setAffected(e.target.value !== '' && Number.isInteger(value) && value >= 0 && value <= 100000000 ? value : null) }} /></label>
      {region && <p className="text-sm">{region.affected_clients == null ? t('cabinet.partialAffected', { clients: region.identified_clients, known: region.identified_signals, total: region.signals }) : t('cabinet.actualAffected', { n: region.affected_clients })}</p>}
      {rateCode === 'bank_average' && <p className="text-sm text-muted">{t('cabinet.bankAverage')}</p>}
      <p className="text-2xl font-semibold num" aria-live="polite">{total == null ? '—' : compactMoney(total > 0 ? -total : total, i18n.language)}</p>
      {result.isFetching && <p role="status" className="text-sm text-muted">{t('cabinet.calculating')}</p>}
      {result.isError && input !== null && <ErrorBox error={result.error} />}
      {data && <p className="text-sm text-muted break-words">{t('cabinet.serverBreakdown', { affected: actualNumber(data.affected_count), detractors: actualNumber(data.detractor_share), noReturn: actualNumber(data.no_return_share), rate: compactMoney(data.rate_rub, i18n.language), premium: compactMoney(data.premium_addon_rub, i18n.language) })}</p>}
      <p className="text-sm">{t('cabinet.formulaHint')}</p>
    </>}
  </div>
}
