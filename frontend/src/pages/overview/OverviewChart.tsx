import { useCallback, useEffect, useRef } from 'react'
import { init, type EChartsOption } from 'echarts'
import { useTranslation } from 'react-i18next'
import type { Schemas } from '@/shared/api/client'
import { tEnum } from '@/shared/i18n'

export function OverviewChart({ data, kind }: { data: Schemas['CxIndex']; kind: 'channels' | 'flow' }) {
  const root = useRef<HTMLDivElement>(null)
  const { t, i18n } = useTranslation()
  const time = useCallback((value: string) => new Intl.DateTimeFormat(i18n.language, { timeZone: 'Europe/Moscow', hour: '2-digit', minute: '2-digit' }).format(new Date(value)), [i18n.language])
  useEffect(() => {
    if (!root.current) return
    const element = root.current, chart = init(element, undefined, { renderer: 'svg' })
    const option: EChartsOption = {
      animation: false, color: ['rgb(var(--brand))', 'rgb(var(--ok))', 'rgb(var(--warn))', 'rgb(var(--danger))', 'rgb(var(--ink))'], textStyle: { color: 'currentColor' }, aria: { enabled: true },
      tooltip: { trigger: kind === 'flow' ? 'axis' : 'item', renderMode: 'richText' },
      ...(kind === 'channels' ? {
        legend: { bottom: 0, type: 'scroll', textStyle: { color: 'currentColor' } },
        series: [{ type: 'pie', radius: ['35%', '62%'], center: ['50%', '43%'], label: { show: false },
          data: data.channel_mix.map(row => ({ name: tEnum('channel', row.channel_code), value: row.signals })),
          itemStyle: { borderColor: 'rgb(var(--ink))', borderWidth: 1, decal: { symbol: 'rect' } } }],
      } : {
        grid: { left: 42, right: 12, top: 18, bottom: 45 },
        xAxis: { type: 'category', data: data.flow.map(row => time(row.ends_sim)), axisLabel: { color: 'currentColor', hideOverlap: true } },
        yAxis: { type: 'value', minInterval: 1, axisLabel: { color: 'currentColor' } },
        series: [{ type: 'bar', name: t('overviewUi.signals'), data: data.flow.map(row => row.signals), color: 'rgb(var(--brand))', itemStyle: { borderColor: 'rgb(var(--ink))', borderWidth: 1, decal: { symbol: 'rect' } } }],
      }),
    }
    chart.setOption(option)
    const observer = new ResizeObserver(() => chart.resize()); observer.observe(element)
    return () => { observer.disconnect(); chart.dispose() }
  }, [data, kind, t, time])
  return <>
    <div className="h-64 min-w-0" ref={root} role="img" aria-label={t(`overviewUi.${kind}`)} />
    <details className="text-sm"><summary className="cursor-pointer rounded focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand">{t('overviewUi.table')}</summary>
      <table className="w-full text-left"><thead><tr><th>{t(kind === 'channels' ? 'overviewUi.channel' : 'overviewUi.hour')}</th><th>{t('overviewUi.signals')}</th></tr></thead><tbody>{kind === 'channels' ? data.channel_mix.map(row => <tr key={row.channel_code}><td>{tEnum('channel', row.channel_code)}</td><td className="num">{row.signals}</td></tr>) : data.flow.map(row => <tr key={row.bucket}><td>{time(row.starts_sim)}–{time(row.ends_sim)}</td><td className="num">{row.signals}</td></tr>)}</tbody></table>
    </details>
  </>
}
