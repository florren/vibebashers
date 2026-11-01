import { useTranslation } from 'react-i18next'
import type { paths } from '@/shared/api/types'
import { useRefs } from '@/shared/api/hooks'
import { ErrorBox } from '@/shared/ui'

type Query = NonNullable<paths['/api/v1/finance/impact/total']['get']['parameters']['query']>
export type ProductSelection = { mode: NonNullable<Query['product_mode']>; codes: string[] }

export function ProductFilter({ value, onChange }: { value: ProductSelection; onChange: (value: ProductSelection) => void }) {
  const { t, i18n } = useTranslation()
  const products = useRefs('products')
  const codes = value.mode === 'all' ? (products.data ?? []).map(p => p.code) : value.codes
  return <details className="card p-4">
    <summary className="cursor-pointer font-semibold">{t('financeProducts.title')} · {value.mode === 'all' ? t('financeProducts.all') : t(`financeProducts.summary.${value.mode}`, { count: codes.length })}</summary>
    <p className="my-3 text-xs text-muted">{t('financeProducts.hint')}</p>
    {products.error && <ErrorBox error={products.error} />}
    <div className="mb-3 flex flex-wrap items-center gap-3">
      <button className="btn btn-sm" disabled={!products.data} onClick={() => onChange({ mode: 'all', codes: [] })}>{t('financeProducts.all')}</button>
      <button className="btn btn-sm" disabled={!products.data} onClick={() => onChange({ mode: value.mode === 'all' ? 'include' : value.mode, codes: [] })}>{t('financeProducts.clear')}</button>
      <label className="text-sm">{t('financeProducts.mode')} <select className="input" disabled={!products.data} value={value.mode === 'all' ? 'include' : value.mode} onChange={e => onChange({ mode: e.target.value as ProductSelection['mode'], codes })}>
        <option value="include">{t('financeProducts.include')}</option>
        <option value="exclude">{t('financeProducts.exclude')}</option>
      </select></label>
    </div>
    <fieldset disabled={!products.data} className="grid max-h-48 grid-cols-1 gap-2 overflow-y-auto sm:grid-cols-2 xl:grid-cols-3">
      <legend className="sr-only">{t('financeProducts.title')}</legend>
      {(products.data ?? []).map(p => <label className="flex min-w-0 cursor-pointer items-center gap-2 text-sm" key={p.code}>
        <input type="checkbox" checked={codes.includes(p.code)} onChange={e => onChange({ mode: value.mode === 'all' ? 'include' : value.mode, codes: (e.target.checked ? [...codes, p.code] : codes.filter(c => c !== p.code)).sort() })} />
        <span>{i18n.language.startsWith('en') ? p.name_en ?? p.name_ru : p.name_ru}</span>
      </label>)}
    </fieldset>
  </details>
}
