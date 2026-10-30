import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { api, type Schemas } from '@/shared/api/client'
import { useEconomicsSettings, useRefs } from '@/shared/api/hooks'
import { StepEconomics } from '@/pages/setup/SetupPage'
import { DashboardTab } from '@/pages/workspace/DashboardTab'
import { ErrorBox, Tabs } from '@/shared/ui'
import { formatMoney as fmtRub } from './money'

export function EconomicsPage() {
  const { t } = useTranslation()
  const [tab, setTab] = useState<'assumptions' | 'fact'>('assumptions')
  const [affected, setAffected] = useState(12)
  const [product, setProduct] = useState('deposit')
  const [system, setSystem] = useState('')
  const [segment, setSegment] = useState('vip')
  const [shares, setShares] = useState({ detractor: 0.1, noReturn: 0.5 })
  const settings = useEconomicsSettings()
  const products = useRefs('products')
  const systems = useRefs('systems')
  const segments = useRefs('segments')
  useEffect(() => { if (settings.data) setShares({ detractor: settings.data.detractor_share ?? 0.1, noReturn: settings.data.no_return_share ?? 0.5 }) }, [settings.data])
  const result = useQuery({ queryKey: ['economics-preview', affected, product, system, segment, shares, settings.dataUpdatedAt], queryFn: () => api<Schemas['IncidentEconomics']>('/api/metrics/economics/preview', { query: { affected, product: product || undefined, system: system || undefined, segment: segment || undefined, detractor_share: shares.detractor, no_return_share: shares.noReturn } }) })
  return <div className="h-full overflow-auto p-4"><div className="mx-auto max-w-6xl space-y-4">
    <h1 className="text-xl font-semibold">{t('calculator.title')}</h1>
    <Tabs value={tab} onChange={setTab} items={[{ id: 'assumptions', label: t('calculator.assumptions') }, { id: 'fact', label: t('dash.fact.title') }]} />
    {tab === 'fact' ? <DashboardTab /> : <>
      <section className="card space-y-3 p-4">
        <button className="btn btn-sm" onClick={() => { setAffected(12); setProduct('deposit'); setSystem(''); setSegment('vip'); setShares({ detractor: 0.1, noReturn: 0.5 }) }}>{t('calculator.preset')}</button>
        <div className="grid gap-3 sm:grid-cols-3">
          <label>{t('incidentEconomics.affected')}<input className="input w-full" type="number" min="0" max="100000000" value={affected} onChange={e => setAffected(Number(e.target.value))} /></label>
          {([{ value: product, change: setProduct, data: products.data, label: 'calculator.product' }, { value: system, change: setSystem, data: systems.data, label: 'calculator.system' }, { value: segment, change: setSegment, data: segments.data, label: 'calculator.segment' }] as const).map(field => <label key={field.label}>{t(field.label)}<select className="input w-full" value={field.value} onChange={e => field.change(e.target.value)}><option value="">—</option>{field.data?.map(item => <option key={item.code} value={item.code}>{item.name_ru ?? item.code}</option>)}</select></label>)}
          <label>{t('incidentEconomics.detractors')}<input className="input w-full" type="number" min="0" max="1" step="0.01" value={shares.detractor} onChange={e => setShares({ ...shares, detractor: Number(e.target.value) })} /></label>
          <label>{t('incidentEconomics.noReturn')}<input className="input w-full" type="number" min="0" max="1" step="0.01" value={shares.noReturn} onChange={e => setShares({ ...shares, noReturn: Number(e.target.value) })} /></label>
        </div>
        {result.isError && <ErrorBox error={result.error} />}
        {result.data && <><p className="text-3xl num">{fmtRub(result.data.potential_loss_rub)}</p><p className="font-mono text-sm">{result.data.formula_ru}</p><p className="text-xs text-muted">{result.data.rate_reason}</p></>}
        <p className="text-xs text-muted">{t('incidentEconomics.estimate')}</p>
      </section>
      <StepEconomics />
    </>}
  </div></div>
}
