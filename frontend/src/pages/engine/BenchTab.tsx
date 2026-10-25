import { clsx } from 'clsx'
import { init, type EChartsOption } from 'echarts'
import { Download, Play, X } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { BenchRun, BenchRunAccepted, BenchRunCreate, BenchRunDetail, LlmApiKey, LlmProfileT, SentimentBenchReport } from '@/shared/api/client'
import { useBenchCancel, useBenchDatasets, useBenchDryRun, useBenchRun, useBenchRuns, useBenchSentiment, useBenchStart, useLlmKeys, useLlmProfiles } from '@/shared/api/hooks'
import { Empty, ErrorBox, Json, SkeletonRows } from '@/shared/ui'

/** Семёрка сравнения (ТЗ 14.3), затем остальные активные, включая local_openai. */
const PROFILE_ORDER = ['gigachat_ultra', 'gigachat_lightning', 'gigachat_pro', 'or_nemotron_ultra', 'or_owl_alpha', 'or_gpt_oss_120b', 'mock'] as const

const DEFAULT_ON = new Set<string>(PROFILE_ORDER)

const METRIC_KEYS = [
  'accuracy_type',
  'accuracy_product',
  'accuracy_system',
  'accuracy_criticality',
  'accuracy_route',
  'recall_critical',
  'json_valid_rate',
  'tool_success_rate',
  'retries_avg',
  'fallback_rate',
  'p50_ms',
  'p95_ms',
  'tokens_total',
  'cost_estimate',
  'stability',
] as const

type MetricKey = (typeof METRIC_KEYS)[number]

const HIGHER = new Set<MetricKey>([
  'accuracy_type',
  'accuracy_product',
  'accuracy_system',
  'accuracy_criticality',
  'accuracy_route',
  'recall_critical',
  'json_valid_rate',
  'tool_success_rate',
  'stability',
])

const RATE_KEYS: MetricKey[] = [
  'accuracy_type',
  'accuracy_product',
  'accuracy_system',
  'accuracy_criticality',
  'accuracy_route',
  'recall_critical',
  'json_valid_rate',
  'tool_success_rate',
  'fallback_rate',
  'stability',
]

const CHART_GREEN = '#21A038'
const CHART_BLUE = '#0098F8'

type ForecastItem = NonNullable<BenchRunAccepted['forecast']>[number]
type BenchCase = NonNullable<BenchRunDetail['results']>[number]

function profileRank(code: string): number {
  const index = PROFILE_ORDER.indexOf(code as (typeof PROFILE_ORDER)[number])
  return index === -1 ? PROFILE_ORDER.length : index
}

function activeProfiles(list: LlmProfileT[]): LlmProfileT[] {
  return list
    .filter((profile) => profile.is_active === true)
    .slice()
    .sort((a, b) => profileRank(a.code) - profileRank(b.code) || a.code.localeCompare(b.code))
}

function latestDone(runs: BenchRun[], code: string): BenchRun | undefined {
  let best: BenchRun | undefined
  for (const run of runs) {
    if (run.llm_profile_code !== code || run.status !== 'done') continue
    if (!best) {
      best = run
      continue
    }
    const nextAt = run.finished_at ?? ''
    const bestAt = best.finished_at ?? ''
    if (nextAt > bestAt || (nextAt === bestAt && (run.id ?? 0) > (best.id ?? 0))) best = run
  }
  return best
}

function readMetric(run: BenchRun | undefined, key: MetricKey): number | null {
  const value = run?.metrics?.[key]
  return value == null ? null : value
}

function fmtMetric(key: MetricKey, value: number | null): string {
  if (value == null) return '—'
  if (key === 'p50_ms' || key === 'p95_ms' || key === 'tokens_total') return String(Math.round(value))
  if (key === 'cost_estimate' || key === 'retries_avg') return value.toFixed(2)
  return value.toFixed(3)
}

function clamp01(value: number | null): number {
  if (value == null) return 0
  return Math.min(1, Math.max(0, value))
}

function sameIds(left: readonly number[] | undefined, right: readonly number[]): boolean {
  if (!left || left.length !== right.length) return false
  const a = [...left].sort((x, y) => x - y)
  const b = [...right].sort((x, y) => x - y)
  return a.every((value, index) => value === b[index])
}

function orderColumns(profiles: LlmProfileT[], runs: BenchRun[], sortKey: MetricKey | null): LlmProfileT[] {
  if (!sortKey) return profiles
  const higher = HIGHER.has(sortKey)
  return profiles.slice().sort((a, b) => {
    const av = readMetric(latestDone(runs, a.code), sortKey)
    const bv = readMetric(latestDone(runs, b.code), sortKey)
    if (av == null && bv == null) return profileRank(a.code) - profileRank(b.code)
    if (av == null) return 1
    if (bv == null) return -1
    if (av !== bv) return higher ? bv - av : av - bv
    return profileRank(a.code) - profileRank(b.code)
  })
}

function bestOf(profiles: LlmProfileT[], runs: BenchRun[], key: MetricKey): number | null {
  let best: number | null = null
  const higher = HIGHER.has(key)
  for (const profile of profiles) {
    const value = readMetric(latestDone(runs, profile.code), key)
    if (value == null) continue
    if (best == null || (higher ? value > best : value < best)) best = value
  }
  return best
}

function currentForecast(
  pending: boolean,
  variables: BenchRunCreate | undefined,
  data: BenchRunAccepted | undefined,
  datasetId: number | null,
  ids: number[],
  repeats: number,
): ForecastItem[] | null {
  if (pending || datasetId == null || !variables || !data) return null
  if (variables.dataset_id !== datasetId || (variables.repeats ?? 1) !== repeats) return null
  if (!sameIds(variables.llm_profile_ids, ids)) return null
  return data.forecast ?? []
}

function useEChart(option: EChartsOption | null) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const node = ref.current
    if (!node || option == null) return
    const chart = init(node)
    chart.setOption(option)
    return () => {
      chart.dispose()
    }
  }, [option])
  return ref
}

function codeById(profiles: LlmProfileT[], id: number | undefined): string {
  if (id == null) return '—'
  return profiles.find((profile) => profile.id === id)?.code ?? String(id)
}

/** Вкладка «Бенчмарки» на /engine (T-130, ТЗ 14.3): живой API bench/*, без своего маршрута. */
export function BenchTab() {
  const { t } = useTranslation()
  const profilesQ = useLlmProfiles()
  const keysQ = useLlmKeys()
  const datasetsQ = useBenchDatasets()
  const dry = useBenchDryRun()
  const start = useBenchStart()
  const cancel = useBenchCancel()
  const runsQ = useBenchRuns(start.isPending)
  const sentimentQ = useBenchSentiment()
  const [picked, setPicked] = useState<number[] | null>(null)
  const [datasetId, setDatasetId] = useState<number | null>(null)
  const [repeats, setRepeats] = useState(1)
  const [sortKey, setSortKey] = useState<MetricKey | null>(null)
  const [chosenId, setChosenId] = useState<number | null>(null)
  const { mutate: dryMutate } = dry

  const profiles = useMemo(() => activeProfiles(profilesQ.data ?? []), [profilesQ.data])
  const datasets = datasetsQ.data ?? []
  const runs = useMemo(() => runsQ.data ?? [], [runsQ.data])
  const activeDataset = datasetId ?? datasets[0]?.id ?? null
  const defaultIds = useMemo(() => profiles.flatMap((profile) => (profile.id != null && DEFAULT_ON.has(profile.code) ? [profile.id] : [])), [profiles])
  const selectedIds = picked ?? defaultIds
  const columns = useMemo(() => orderColumns(profiles, runs, sortKey), [profiles, runs, sortKey])
  const forecast = currentForecast(dry.isPending, dry.variables, dry.data, activeDataset, selectedIds, repeats)
  const shortage = (forecast ?? []).filter((item) => item.fits_limits === false)
  const quiet = (forecast ?? []).filter((item) => item.fits_limits !== false && Boolean(item.warning?.trim()))
  const startDisabled = forecast == null || shortage.length > 0 || activeDataset == null || selectedIds.length === 0 || start.isPending
  const autoId = useMemo(() => runs.find((run) => run.status === 'done' && run.id != null)?.id ?? null, [runs])
  const detailId = chosenId ?? autoId
  const detailQ = useBenchRun(detailId)

  useEffect(() => {
    if (activeDataset == null || selectedIds.length === 0) return
    dryMutate({ dataset_id: activeDataset, llm_profile_ids: selectedIds, repeats })
  }, [activeDataset, selectedIds, repeats, dryMutate])

  const radarOption = useMemo<EChartsOption | null>(() => {
    if (columns.length === 0) return null
    return {
      color: [CHART_GREEN, CHART_BLUE],
      legend: { type: 'scroll' },
      radar: { indicator: RATE_KEYS.map((key) => ({ name: t(`bench.metric.${key}`), min: 0, max: 1 })) },
      series: [
        {
          type: 'radar',
          data: columns.map((profile, index) => ({
            name: profile.code,
            value: RATE_KEYS.map((key) => clamp01(readMetric(latestDone(runs, profile.code), key))),
            lineStyle: { color: index % 2 === 0 ? CHART_GREEN : CHART_BLUE },
            itemStyle: { color: index % 2 === 0 ? CHART_GREEN : CHART_BLUE },
          })),
        },
      ],
    }
  }, [columns, runs, t])

  const barOption = useMemo<EChartsOption | null>(() => {
    if (columns.length === 0) return null
    return {
      color: [CHART_GREEN, CHART_BLUE],
      legend: {},
      tooltip: { trigger: 'axis' },
      xAxis: { type: 'category', data: columns.map((profile) => profile.code) },
      yAxis: { type: 'value' },
      series: [
        {
          type: 'bar',
          name: t('bench.metric.p50_ms'),
          itemStyle: { color: CHART_GREEN },
          data: columns.map((profile) => readMetric(latestDone(runs, profile.code), 'p50_ms') ?? 0),
        },
        {
          type: 'bar',
          name: t('bench.metric.p95_ms'),
          itemStyle: { color: CHART_BLUE },
          data: columns.map((profile) => readMetric(latestDone(runs, profile.code), 'p95_ms') ?? 0),
        },
      ],
    }
  }, [columns, runs, t])

  const radarRef = useEChart(radarOption)
  const barRef = useEChart(barOption)

  if (profilesQ.isPending || datasetsQ.isPending || runsQ.isPending) return <SkeletonRows />
  if (profilesQ.isError) return <ErrorBox error={profilesQ.error} />
  if (datasetsQ.isError) return <ErrorBox error={datasetsQ.error} />
  if (runsQ.isError) return <ErrorBox error={runsQ.error} />

  const live = runs.filter((run) => run.status === 'queued' || run.status === 'running')

  const toggle = (id: number) => {
    setPicked((prev) => {
      const base = prev ?? defaultIds
      return base.includes(id) ? base.filter((item) => item !== id) : [...base, id]
    })
  }

  return (
    <div className="space-y-4 p-4">
      <div className="flex flex-wrap items-end gap-3">
        <label className="text-xs text-muted">
          {t('bench.dataset')}
          <select
            className="mt-1 block h-8 rounded-md border border-line bg-surface px-2 text-sm text-ink"
            value={activeDataset ?? ''}
            onChange={(event) => setDatasetId(Number(event.target.value))}
          >
            {datasets.map((dataset) => (
              <option key={dataset.id} value={dataset.id}>
                {dataset.title_ru || dataset.code}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs text-muted">
          {t('bench.repeats')}
          <select
            className="mt-1 block h-8 rounded-md border border-line bg-surface px-2 text-sm text-ink"
            value={repeats}
            onChange={(event) => setRepeats(Number(event.target.value))}
          >
            <option value={1}>1</option>
            <option value={2}>2</option>
            <option value={3}>3</option>
          </select>
        </label>
        <button type="button" className="btn btn-primary btn-sm" aria-label={t('bench.start')} disabled={startDisabled} onClick={() => activeDataset != null && start.mutate({ dataset_id: activeDataset, llm_profile_ids: selectedIds, repeats })}>
          <Play size={14} aria-hidden /> {t('bench.start')}
        </button>
      </div>
      <fieldset className="flex flex-wrap gap-3">
        <legend className="text-xs font-semibold uppercase tracking-wide text-muted">{t('bench.profiles')}</legend>
        {profiles.map((profile) =>
          profile.id == null ? null : (
            <label key={profile.id} className="flex items-center gap-1 text-xs">
              <input type="checkbox" checked={selectedIds.includes(profile.id)} onChange={() => toggle(profile.id!)} />
              {profile.code}
            </label>
          ),
        )}
      </fieldset>
      <section className="space-y-2">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">{t('bench.forecast')}</h3>
        {dry.isError && <ErrorBox error={dry.error} />}
        {forecast && (
          <ul className="text-xs text-muted">
            {forecast.map((item, index) => (
              <li key={`${item.llm_profile_id ?? 'x'}-${index}`}>
                {codeById(profiles, item.llm_profile_id)} · {item.est_tokens ?? '—'} · {item.est_requests ?? '—'}
              </li>
            ))}
          </ul>
        )}
        {shortage.length > 0 && (
          <div role="alert" className="rounded-lg border border-warn/40 bg-warn/10 px-3 py-2 text-sm">
            <div>{t('bench.limitWarning')}</div>
            {shortage.map((item, index) => (
              <div key={index}>{item.warning}</div>
            ))}
          </div>
        )}
        {quiet.map((item, index) => (
          <p key={index} className="text-xs text-muted">
            {item.warning}
          </p>
        ))}
      </section>
      {live.length > 0 && (
        <section className="space-y-2">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">{t('bench.active')}</h3>
          {live.map((run) => {
            const pct = Math.round(Math.min(1, Math.max(0, run.progress ?? 0)) * 100)
            return (
              <div key={run.id ?? run.llm_profile_code} className="flex items-center gap-2">
                <span className="w-40 truncate font-mono text-xs">{run.llm_profile_code}</span>
                <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-raised" role="progressbar" aria-label={t('bench.progress')} aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}>
                  <div className="h-full bg-brand" style={{ width: `${pct}%` }} />
                </div>
                {run.id != null && (
                  <button type="button" className="btn btn-sm" aria-label={t('bench.cancel')} onClick={() => cancel.mutate(run.id!)}>
                    <X size={14} aria-hidden /> {t('bench.cancel')}
                  </button>
                )}
                {run.id != null && <ExportLinks id={run.id} />}
              </div>
            )
          })}
        </section>
      )}
      {profiles.length === 0 ? (
        <Empty title={t('bench.empty')} />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-xs">
            <thead>
              <tr>
                <th scope="col" className="px-2 py-1 text-left">
                  {t('bench.metrics')}
                </th>
                {columns.map((profile) => (
                  <th key={profile.code} scope="col" className="px-2 py-1 text-right">
                    <button type="button" className="font-mono" onClick={() => { const run = latestDone(runs, profile.code); if (run?.id != null) setChosenId(run.id) }}>
                      {profile.code}
                    </button>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {METRIC_KEYS.map((key) => {
                const best = sortKey === key ? bestOf(columns, runs, key) : null
                return (
                  <tr key={key} className="border-t border-line">
                    <th scope="row" className="px-2 py-1 text-left font-normal">
                      <button type="button" onClick={() => setSortKey(key)}>
                        {t(`bench.metric.${key}`)}
                      </button>
                      <span className="mt-0.5 block text-[10px] text-muted">{HIGHER.has(key) ? t('bench.higherBetter') : t('bench.lowerBetter')}</span>
                    </th>
                    {columns.map((profile) => {
                      const value = readMetric(latestDone(runs, profile.code), key)
                      const marked = best != null && value === best
                      return (
                        <td key={profile.code} className={clsx('num px-2 py-1 text-right', marked && 'bg-brand-soft')}>
                          {fmtMetric(key, value)}
                        </td>
                      )
                    })}
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
      <div ref={radarRef} className="h-64 w-full" />
      <div ref={barRef} className="h-64 w-full" />
      <section className="space-y-2">
        {detailId != null && <ExportLinks id={detailId} />}
        {detailQ.isLoading && <SkeletonRows n={2} />}
        {detailQ.isError && <ErrorBox error={detailQ.error} />}
        {detailQ.data?.results?.map((item) => (
          <CaseCard key={item.case_id ?? item.text} item={item} />
        ))}
      </section>
      <section className="space-y-2">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">{t('bench.limits')}</h3>
        {keysQ.isError && <ErrorBox error={keysQ.error} />}
        {keysQ.isPending && <SkeletonRows n={2} />}
        {keysQ.data && <KeysBlock profiles={profiles} keys={keysQ.data} />}
      </section>
      <section className="space-y-2">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">{t('bench.sentiment')}</h3>
        {sentimentQ.isPending && <SkeletonRows n={2} />}
        {sentimentQ.isError && <ErrorBox error={sentimentQ.error} />}
        {sentimentQ.data && <SentimentBlock report={sentimentQ.data} />}
      </section>
    </div>
  )
}

function ExportLinks({ id }: { id: number }) {
  const { t } = useTranslation()
  return (
    <span className="inline-flex gap-1">
      <a className="btn btn-ghost btn-sm" href={`/api/bench/runs/${id}/export?format=csv`} aria-label={`${t('bench.export')} ${t('bench.csv')}`}>
        <Download size={14} aria-hidden /> {t('bench.csv')}
      </a>
      <a className="btn btn-ghost btn-sm" href={`/api/bench/runs/${id}/export?format=json`} aria-label={`${t('bench.export')} ${t('bench.json')}`}>
        <Download size={14} aria-hidden /> {t('bench.json')}
      </a>
    </span>
  )
}

function CaseCard({ item }: { item: BenchCase }) {
  const { t } = useTranslation()
  const correct = (item.correct ?? {}) as Record<string, boolean>
  const wrong = Object.entries(correct).filter(([, ok]) => ok === false)
  const showErrors = wrong.length > 0 || item.json_valid_first_try === false || item.fallback_mock === true
  return (
    <article className="card space-y-2 p-3">
      <h4 className="text-sm font-medium">
        {t('bench.case')} #{item.case_id ?? '—'}
      </h4>
      <p className="text-sm">{item.text}</p>
      <div className="text-xs text-muted">{t('bench.gold')}</div>
      <Json value={item.gold} />
      <div className="text-xs text-muted">{t('bench.predicted')}</div>
      <Json value={item.predicted} />
      {showErrors && (
        <div className="text-sm">
          <div className="text-xs text-muted">{t('bench.errors')}</div>
          {wrong.map(([field]) => (
            <div key={field}>{field}</div>
          ))}
          {item.json_valid_first_try === false && <div>{t('bench.jsonInvalid')}</div>}
          {item.fallback_mock === true && <div>{t('bench.fallback')}</div>}
        </div>
      )}
    </article>
  )
}

function KeysBlock({ profiles, keys }: { profiles: LlmProfileT[]; keys: LlmApiKey[] }) {
  const { t } = useTranslation()
  return (
    <ul className="space-y-2 text-xs">
      {profiles.map((profile) => {
        const key = keys.find((item) => item.id === profile.api_key_id)
        return (
          <li key={profile.code} className="card space-y-1 p-3">
            <div className="font-mono">{profile.code}</div>
            <div>
              {t('bench.apiKey')}: {profile.api_key_id ?? '—'}
            </div>
            <div>
              {t('bench.rpm')}: {profile.rpm_limit ?? '—'}
            </div>
            <div>
              {t('bench.rpd')}: {profile.rpd_limit ?? '—'}
            </div>
            {key?.provider === 'gigachat' && (
              <div>
                {t('bench.tokens')}: {key.tokens_used ?? 0}/{key.tokens_limit ?? '—'}
              </div>
            )}
            {key?.provider === 'openai_compatible' && (
              <>
                <div>
                  {t('bench.balance')}: {key.balance_usd ?? '—'}
                </div>
                <div>
                  {t('bench.requests')}: {key.requests_today ?? 0}/{key.rpd_limit ?? '—'}
                </div>
              </>
            )}
          </li>
        )
      })}
    </ul>
  )
}

function SentimentBlock({ report }: { report: SentimentBenchReport }) {
  const { t } = useTranslation()
  const providers = report.providers ?? []
  if (providers.length === 0) return <Empty title={t('bench.empty')} />
  return (
    <ul className="space-y-2">
      {providers.map((provider, index) => (
        <li key={`${provider.provider ?? ''}-${provider.model ?? ''}-${index}`} className="card space-y-1 p-3 text-xs">
          <div>
            {provider.provider} · {provider.model}
          </div>
          <div>
            {t('bench.accuracy')}: {provider.accuracy ?? '—'}
          </div>
          <div>
            {t('bench.passed')}: {provider.passed ? t('bench.yes') : t('bench.no')}
          </div>
          <div>{t('bench.confusion')}</div>
          <Json value={provider.confusion} />
        </li>
      ))}
    </ul>
  )
}
