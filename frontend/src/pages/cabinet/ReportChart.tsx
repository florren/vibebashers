import { useEffect, useRef } from 'react'
import { init, type EChartsOption } from 'echarts'
import { useTranslation } from 'react-i18next'
import type { Schemas } from '@/shared/api/client'

type Report = Schemas['CabinetReport']

/** SVG с маркерами/штриховкой; неизвестные деньги не рисуются как нулевая ось. */
export function ReportChart({ report, code }: { report: Report; code: Report['charts'][number]['code'] }) {
  const element = useRef<HTMLDivElement>(null)
  const { t } = useTranslation()
  const data = report.overview
  const hasPotential = (code === 'daily' ? data.daily : data.monthly).some(row => row.potential_loss_rub != null)
  const hasPrevented = code === 'daily' && data.daily.some(row => row.prevented_loss_rub != null)
  const hasMoney = hasPotential || hasPrevented
  const hasValues = code === 'sources' ? data.sources.length > 0 : code === 'monthly' ? data.monthly.length > 0 : hasMoney
  useEffect(() => {
    const node = element.current
    if (!node || !hasValues) return
    const chart = init(node, undefined, { renderer: 'svg' })
    // Координаты/деления оси — графическое приближение; точные суммы остаются в KPI и экспорте.
    const axis = { color: '#202020', fontSize: 9, formatter: (value: number) => new Intl.NumberFormat(report.lang, { notation: 'compact', maximumFractionDigits: 1 }).format(value) }
    const bars = { name: t('cabinet.signals'), type: 'bar' as const, color: '#444', itemStyle: { decal: { symbol: 'rect', dashArrayX: [1, 0], dashArrayY: [2, 4] } } }
    const option: EChartsOption = {
      animation: false, aria: { enabled: true }, textStyle: { color: '#202020', fontSize: 10 },
      grid: { left: 58, right: code === 'monthly' ? 58 : 12, top: 25, bottom: code === 'sources' ? 60 : 25 },
      legend: { textStyle: { color: '#202020', fontSize: 10 } },
      xAxis: { type: 'category', axisLabel: { color: '#202020', fontSize: 9, rotate: code === 'sources' ? 20 : 0 }, data: code === 'sources' ? data.sources.map(row => row.platform?.[report.lang === 'en' ? 'name_en' : 'name_ru'] ?? t('cabinet.unknownSource')) : code === 'daily' ? data.daily.map(row => row.day.slice(5)) : data.monthly.map(row => row.month.slice(0, 7)) },
      yAxis: [{ type: 'value', show: code === 'sources' || hasMoney, axisLabel: axis, name: code === 'sources' ? t('cabinet.signals') : 'RUB' }, ...(code === 'monthly' ? [{ type: 'value' as const, axisLabel: axis, name: t('cabinet.signals') }] : [])],
      series: code === 'sources' ? [{ ...bars, data: data.sources.map(row => row.signals) }] : [
        ...(hasPotential ? [{ name: t('cabinet.loss'), type: 'line' as const, color: '#222', symbol: 'triangle', symbolSize: 5, connectNulls: false, data: (code === 'daily' ? data.daily : data.monthly).map(row => row.potential_loss_rub) }] : []),
        ...(hasPrevented ? [{ name: t('cabinet.prevented'), type: 'line' as const, color: '#555', symbol: 'circle', symbolSize: 5, lineStyle: { type: 'dashed' as const }, connectNulls: false, data: data.daily.map(row => row.prevented_loss_rub) }] : []),
        ...(code === 'monthly' ? [{ ...bars, yAxisIndex: 1, data: data.monthly.map(row => row.signals) }] : []),
      ],
    }
    chart.setOption(option)
    const resize = () => chart.resize()
    const observer = new ResizeObserver(resize); observer.observe(node)
    window.addEventListener('beforeprint', resize)
    return () => { observer.disconnect(); window.removeEventListener('beforeprint', resize); chart.dispose() }
  }, [report, code, t, data, hasValues, hasMoney, hasPotential, hasPrevented])
  return <div className="report-chart" data-report-chart={code} ref={element} role="img" aria-label={report.charts.find(row => row.code === code)?.title_insight}>{!hasValues && <p className="pt-16 text-center">{t(code === 'daily' ? 'cabinet.noSavedEconomics' : 'cabinet.noData')}</p>}</div>
}
