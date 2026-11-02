import { compactMoney } from './format'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useEconomicsSettings } from '@/shared/api/hooks'
import { ErrorBox, Skeleton } from '@/shared/ui'
import type { Overview } from './api'

/** Только сценарные допущения из действующих settings/rates; никаких финансовых записей. */
export function CabinetCalculator({ line, region }: { line: Overview['product_lines'][number] | undefined; region: Overview['regions'][number] | undefined }) {
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
  const rate = rates.find(row => row.code === rateCode)
  const detractors = settings.data?.detractor_share
  const noReturn = settings.data?.no_return_share
  const total = affected != null && rate?.rate_rub != null && detractors != null && noReturn != null ? affected * detractors * noReturn * rate.rate_rub : null
  return <div className="space-y-3">
    <p className="text-sm text-muted">{t('cabinet.calculatorHint')}</p>
    {settings.isError ? <ErrorBox error={settings.error} /> : settings.isPending ? <Skeleton className="h-20" /> : <>
      <label className="block text-sm">{t('cabinet.rate')}<select className="input mt-1 w-full" value={rateCode ?? ''} onChange={e => setRateCode(e.target.value || null)}><option value="">{t('cabinet.chooseRate')}</option>{rates.map(row => <option key={row.code} value={row.code}>{i18n.language.startsWith('en') ? row.name_en : row.name_ru} · {compactMoney(row.rate_rub, i18n.language)}</option>)}</select></label>
      <label className="block text-sm">{t('incidentEconomics.affected')}<input className="input mt-1 w-full" type="number" min={0} max={100000000} step={1} value={affected ?? ''} onChange={e => { const value = Number(e.target.value); setAffected(e.target.value !== '' && Number.isInteger(value) && value >= 0 && value <= 100000000 ? value : null) }} /></label>
      {region && <p className="text-sm">{region.affected_clients == null ? t('cabinet.partialAffected', { clients: region.identified_clients, known: region.identified_signals, total: region.signals }) : t('cabinet.actualAffected', { n: region.affected_clients })}</p>}
      {rateCode === 'bank_average' && <p className="text-sm text-muted">{t('cabinet.bankAverage')}</p>}
      <p className="text-2xl font-semibold num" aria-live="polite">{total == null ? '—' : `−${compactMoney(total, i18n.language)}`}</p>
      <p className="text-sm text-muted break-words">{affected ?? '—'} × {detractors ?? '—'} × {noReturn ?? '—'} × {rate?.rate_rub ?? '—'} ₽</p>
      <p className="text-sm">{t('cabinet.formulaHint')}</p>
    </>}
  </div>
}
