import { useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import { ApiConnectionError, ApiError, api, qs, type Schemas } from '@/shared/api/client'
import { useViewPreset } from '@/shared/layout/preset'
import { Empty, ErrorBox, Skeleton } from '@/shared/ui'
import { fmtSimMoscow } from '@/shared/lib/format'
import { cabinetPercent } from './format'
import { formatExactRub } from '@/shared/lib/exactMoney'
import { ReportChart } from './ReportChart'
import './report.css'

type Report = Schemas['CabinetReport']

export function ReportPage() {
  const { productLine = '' } = useParams()
  const [params] = useSearchParams()
  const { t, i18n } = useTranslation()
  const role = useViewPreset(state => state.role)
  const lang = i18n.language.startsWith('en') ? 'en' : 'ru'
  const binding = localStorage.getItem('cx.ui.productLine')
  const headers = { 'X-Cx-Role': role, ...(binding ? { 'X-Cx-Product-Line': binding } : {}) }
  const query = { product_line: productLine, period: params.get('period') ?? 'month', run_id: params.get('run_id') ?? 'current', lang }
  const report = useQuery({ queryKey: ['cabinet', 'report', query, headers], queryFn: ({ signal }) => api<Report>('/api/cabinet/report', { query, headers, signal }), staleTime: Infinity })
  const [exportError, setExportError] = useState<unknown>(null)
  const [exporting, setExporting] = useState(false)
  const download = async (format: 'json' | 'xlsx') => {
    setExportError(null); setExporting(true)
    try {
      let response: Response
      try { response = await fetch('/api/cabinet/report' + qs({ ...query, format }), { headers }) }
      catch (error) { throw new ApiConnectionError(error) }
      if (!response.ok) { const problem = await response.json().catch(() => null); throw new ApiError(response.status, problem, String(response.status)) }
      const blob = await response.blob(), url = URL.createObjectURL(blob)
      const a = document.createElement('a'); a.href = url; a.download = `cabinet-report.${format}`; a.click()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (error) { setExportError(error) } finally { setExporting(false) }
  }
  const data = report.isError ? undefined : report.data
  const line = data?.overview.product_lines.find(row => row.code === productLine)
  const date = data ? new Intl.DateTimeFormat(lang, { timeZone: 'Europe/Moscow', dateStyle: 'medium', timeStyle: 'short' }).format(new Date(data.method.generated_sim)) : ''
  const number = (value: number | null) => value == null ? '—' : new Intl.NumberFormat(lang).format(value)
  const exact = (kpi: Report['kpi'][number]) => data ? formatExactRub(data.money_exact.kpi[kpi.code === 'loss' ? 'potential_loss_rub' : 'prevented_loss_rub'], lang) : { compact: '—', exact: '—' }
  const value = (kpi: Report['kpi'][number]) => kpi.unit === 'RUB' ? exact(kpi).compact : kpi.unit === '%' ? cabinetPercent(kpi.value, lang) : number(kpi.value)
  const short = (value: string, limit = 100) => Array.from(value).length > limit ? Array.from(value).slice(0, limit).join('') + '…' : value
  const footer = (page: number) => <footer className="report-footer">{date} · {t('report.synthetic')} · {page} / 3</footer>
  return <main className="report-root" data-report>
    <nav className="report-controls" aria-label={t('report.controls')}>
      <Link className="btn" to={{ pathname: `/cabinet/${encodeURIComponent(productLine)}`, search: params.toString() }}>{t('report.back')}</Link>
      <button className="btn" onClick={() => void i18n.changeLanguage(lang === 'ru' ? 'en' : 'ru')}>{lang === 'ru' ? 'EN' : 'RU'}</button>
      <button className="btn" disabled={!data} onClick={() => window.print()}>{t('report.pdf')}</button>
      {(['json', 'xlsx'] as const).map(format => <button className="btn" key={format} disabled={!data || exporting} onClick={() => void download(format)}>{t('report.download', { format: format.toUpperCase() })}</button>)}
    </nav>
    <p className="report-controls text-sm">{t('report.exportSnapshot')}</p>
    {report.isError && <ErrorBox error={report.error} />}{exportError != null && <ErrorBox error={exportError} />}
    {report.isPending && <Skeleton className="mx-auto h-64 w-full max-w-3xl" />}
    {data && <>
      <article className="report-paper" data-report-page="1">
        <h1>{t('report.title')} · {line?.[lang === 'en' ? 'name_en' : 'name_ru'] ?? t('cabinet.allLines')}</h1>
        <p className="report-meta">{fmtSimMoscow(data.overview.scope.since_sim)} — {date} · {t(`shell.roles.${data.overview.scope.role}`)} · {t(`cabinet.${data.overview.scope.visibility}`)}</p>
        <section><h2>{t('report.summary')}</h2><ol className="report-summary">{data.summary.map((text, n) => <li key={n}>{text}</li>)}</ol></section>
        <section><h2>{t('report.kpi')}</h2><div className="report-kpis">{data.kpi.map(kpi => <div key={kpi.code}><h3>{kpi.label}</h3><strong title={kpi.unit === 'RUB' ? data.money_exact.kpi[kpi.code === 'loss' ? 'potential_loss_rub' : 'prevented_loss_rub'] ?? undefined : undefined}>{value(kpi)}</strong><p>{kpi.unit === 'RUB' ? <span data-exact-money>{exact(kpi).exact}</span> : kpi.unit}</p><p>{kpi.delta == null ? t('report.deltaUnknown') : `${kpi.delta > 0 ? '↑ +' : kpi.delta < 0 ? '↓ ' : '→ '}${number(kpi.delta)}`}</p><p>{kpi.verdict}</p></div>)}</div></section>
        <p className="report-note">{data.previous.note}</p>{footer(1)}
      </article>
      <article className="report-paper" data-report-page="2">
        <h2>{t('report.charts')}</h2>
        {data.charts.map(chart => <section className="report-figure" key={chart.code}><h3>{chart.title_insight}</h3><ReportChart report={data} code={chart.code} /><p>{chart.note}</p>{chart.code === 'monthly' && <p>{t('cabinet.historyHint')}</p>}</section>)}
        {footer(2)}
      </article>
      <article className="report-paper report-detail" data-report-page="3">
        <section><h2>{t('report.problems')}</h2><p>{t('report.clientCoverage')}</p>{data.top_problems.length ? <table><thead><tr>{['problem', 'clients', 'where', 'status', 'action'].map(key => <th key={key}>{t(`report.${key}`)}</th>)}</tr></thead><tbody>{data.top_problems.map(row => <tr key={row.public_id}><td>{short(row.problem)} ({row.public_id})</td><td>{number(row.clients)}{row.clients == null && <><br />{t('report.identified', { count: row.identified_clients })}</>}</td><td>{row.region}</td><td>{row.status}</td><td>{short(row.action, 80)}<br />{row.team}</td></tr>)}</tbody></table> : <Empty title={t('cabinet.noData')} />}</section>
        <section><h2>{t('report.attention')}</h2><p>{t('report.shownAttention', { shown: Math.min(3, data.attention.length), total: data.attention_total })}</p><ul>{data.attention.slice(0, 3).map(row => <li key={row.public_id}>{row.recommendation}: {short(row.problem)} ({row.public_id}) — {row.team}.</li>)}</ul><p>{data.red_phrase_action}: {data.red_phrase_signals}. {t('report.teamsFromProblems')}</p><ul>{data.red_phrase_attention.slice(0, 2).map(row => <li key={row.public_id}>{data.red_phrase_action}: {short(row.problem)} ({row.public_id}) — {row.team}.</li>)}</ul></section>
        <section><h2>{t('report.method')}</h2><p>{data.method.terms}</p><p>{data.method.formula_note}</p>{data.method.formula_ru.slice(0, 2).map((formula, n) => <p key={n}>{short(formula, 160)}</p>)}<p>{t('report.formulaCount', { shown: Math.min(2, data.method.formula_ru.length), total: data.method.formula_ru.length })}</p>
          <p>{t('report.rules')}: {data.method.rules_version.slice(0, 3).map(row => t('report.ruleVersion', { version: row.version, code: row.code })).join('; ') || data.method.rules_note}</p>
          <p>{t('report.run')}: {data.method.run_public_id.slice(0, 3).map(id => `(${id})`).join(', ') || '—'} · {t('report.version')}: {data.method.app_version}</p>
          <p>{t('report.metadataPreview', { rules: data.method.rules_version.length, runs: data.method.run_public_id.length })}</p><p>{t('report.fullExport')}</p>
        </section>{footer(3)}
      </article>
    </>}
  </main>
}
