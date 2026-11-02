import { useEffect, useRef, useState } from 'react'
import { init, type EChartsOption } from 'echarts'
import { useTranslation } from 'react-i18next'
import type { Overview } from './api'
import { Empty } from '@/shared/ui'

export function CabinetChart({ data }: { data: Overview }) {
  const { t, i18n } = useTranslation()
  const [tab, setTab] = useState<'daily' | 'monthly' | 'sources'>('daily')
  const element = useRef<HTMLDivElement>(null)
  const sourceLabel = (source: Overview['sources'][number]) => source.platform ? i18n.language.startsWith('en') ? source.platform.name_en : source.platform.name_ru : t('cabinet.unknownSource')
  const rows = tab === 'daily' ? data.daily : tab === 'monthly' ? data.monthly : data.sources
  const hasValues = tab === 'sources' ? data.sources.length > 0 : rows.length > 0
  useEffect(() => {
    if (!element.current || !hasValues) return
    const root = element.current
    const chart = init(root, undefined, { renderer: 'svg' })
    const update = () => {
      // SVG наследует актуальный ink и CSS-токены даже во время circadian перехода.
      const text = 'currentColor'
      const loss = 'rgb(var(--danger))'
      const saved = 'rgb(var(--ok))'
      const sourceNames = data.sources.map(source => source.platform ? i18n.language.startsWith('en') ? source.platform.name_en : source.platform.name_ru : t('cabinet.unknownSource'))
      const option: EChartsOption = {
        animation: false, aria: { enabled: true }, tooltip: { trigger: 'axis' },
        textStyle: { color: text }, grid: { left: 64, right: 16, top: 44, bottom: tab === 'sources' ? 74 : 40 },
        legend: { textStyle: { color: text }, type: 'scroll' },
        xAxis: { type: 'category', data: tab === 'sources' ? sourceNames : tab === 'daily' ? data.daily.map(row => row.day.slice(5)) : data.monthly.map(row => row.month.slice(0, 7)), axisLabel: { color: text, rotate: tab === 'sources' ? 25 : 0 } },
        yAxis: { type: 'value', axisLabel: { color: text, formatter: value => new Intl.NumberFormat(i18n.language, { notation: 'compact' }).format(Number(value)) } },
        series: tab === 'sources' ? [{ name: t('cabinet.signals'), type: 'bar', data: data.sources.map(row => row.signals), color: saved, itemStyle: { decal: { symbol: 'rect' } } }] : [
          { name: t('cabinet.loss'), type: 'line', data: (tab === 'daily' ? data.daily : data.monthly).map(row => row.potential_loss_rub), color: loss, symbol: 'triangle', connectNulls: false },
          ...(tab === 'daily' ? [{ name: t('cabinet.prevented'), type: 'line' as const, data: data.daily.map(row => row.prevented_loss_rub), color: saved, symbol: 'circle', connectNulls: false }] : [{ name: t('cabinet.signals'), type: 'bar' as const, data: data.monthly.map(row => row.signals), color: saved }]),
        ],
      }
      chart.setOption(option, true)
    }
    update()
    const size = new ResizeObserver(() => chart.resize()); size.observe(root)
    return () => { size.disconnect(); chart.dispose() }
  }, [data, tab, hasValues, t, i18n.language])
  return <>
    <div className="flex flex-wrap gap-2" role="group" aria-label={t('cabinet.chartTabs')}>
      {(['daily', 'monthly', 'sources'] as const).map(key => <button className="btn btn-sm" key={key} aria-pressed={tab === key} onClick={() => setTab(key)}>{t(`cabinet.${key}`)}</button>)}
    </div>
    <p className="mt-2 text-sm text-muted">{t(tab === 'monthly' ? 'cabinet.historyHint' : tab === 'daily' ? 'cabinet.dailyHint' : 'cabinet.sourcesHint')}</p>
    {hasValues ? <div ref={element} className="h-64 min-w-0" role="img" aria-label={t(`cabinet.${tab}`)} /> : <Empty title={t('cabinet.noData')} />}
    <details className="mt-2 text-sm"><summary className="cursor-pointer rounded focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand">{t('cabinet.chartTable')}</summary>
      <div className="overflow-x-auto"><table className="w-full text-left"><thead><tr><th>{t(tab === 'sources' ? 'cabinet.source' : 'cabinet.period')}</th><th>{t('cabinet.signals')}</th>{tab !== 'sources' && <th>{t('cabinet.loss')}</th>}</tr></thead><tbody>
        {tab === 'sources' ? data.sources.map((row, n) => <tr key={n}><td>{sourceLabel(row)}</td><td>{row.signals}</td></tr>) : tab === 'daily' ? data.daily.map(row => <tr key={row.day}><td>{row.day}</td><td>{row.signals ?? '—'}</td><td>{row.potential_loss_rub ?? '—'}</td></tr>) : data.monthly.map(row => <tr key={row.month}><td>{row.month.slice(0, 7)} · {t(row.is_synthetic ? 'cabinet.aggregates' : 'cabinet.observations')}{row.is_partial ? ` · ${t('cabinet.partial')}` : ''}</td><td>{row.signals}</td><td>{row.potential_loss_rub ?? '—'}</td></tr>)}
      </tbody></table></div>
    </details>
  </>
}
