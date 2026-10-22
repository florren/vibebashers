import { clsx } from 'clsx'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import type { AgentStep } from '@/shared/api/client'
import { useAgentRun } from '@/shared/api/hooks'
import { tEnum } from '@/shared/i18n'
import { fmtMs } from '@/shared/lib/format'
import { Badge, Empty, ErrorBox, Json, Pre, Skeleton } from '@/shared/ui'
import { useWs } from '@/shared/ws/client'

/** Панель «шаги агента» одного прогона: промпт, ответ, инструменты, токены. Используется в карточке инцидента и «Под капотом». */
export function LogPanel({ runId, full }: { runId: number | null; full?: boolean }) {
  const { t } = useTranslation()
  const q = useAgentRun(runId)
  const liveCount = useWs((s) => s.events.filter((e) => e.topic === 'agent' && e.data.agent_run_id === runId).length)
  const run = q.data

  if (runId === null) return <Empty title={t('engine.selectRun')} />
  if (q.isPending)
    return (
      <div className="space-y-2 p-3">
        <Skeleton className="h-8" />
        <Skeleton className="h-8" />
        <Skeleton className="h-8" />
      </div>
    )
  if (q.isError) return <ErrorBox error={q.error} />
  if (!run) return null

  return (
    <div className="flex h-full flex-col">
      <div className="flex h-10 shrink-0 items-center gap-2 border-b border-line px-3 text-xs">
        <span className="font-mono">#{run.id}</span>
        <Badge tone={run.outcome === 'completed' ? 'ok' : run.outcome === 'awaiting_human' ? 'warn' : run.outcome === 'failed' ? 'danger' : 'info'}>
          {tEnum('engine.outcome', run.outcome ?? 'running')}
        </Badge>
        <span className="text-muted">
          {run.llm_profile_code} · {run.prompt_version}
        </span>
        <span className="ml-auto num text-muted">
          {run.total_tokens} {t('engine.tokens')} · {fmtMs(run.total_latency_ms)}
        </span>
        {!full && (
          <Link to={`/engine/${run.id}`} className="btn btn-ghost btn-sm">
            {t('nav.engine')}
          </Link>
        )}
        <span className="sr-only">{liveCount}</span>
      </div>
      <ol className="min-h-0 flex-1 overflow-y-auto">
        {(run.steps ?? []).map((s) => (
          <StepRow key={`${s.seq}-${s.node}`} s={s} full={full} />
        ))}
      </ol>
    </div>
  )
}

function StepRow({ s, full }: { s: AgentStep; full?: boolean }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const tone = s.status === 'ok' ? 'ok' : s.status === 'error' ? 'danger' : s.status === 'waiting' ? 'warn' : 'neutral'
  const tools = s.tool_calls ?? []
  return (
    <li className="border-b border-line">
      <button className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-raised" onClick={() => setOpen((v) => !v)}>
        {open ? <ChevronDown size={13} className="text-faint" /> : <ChevronRight size={13} className="text-faint" />}
        <span className="num w-5 font-mono text-[11px] text-faint">{s.seq}</span>
        <span className={clsx('h-2 w-2 rounded-full', tone === 'ok' ? 'bg-ok' : tone === 'danger' ? 'bg-danger' : tone === 'warn' ? 'bg-warn' : 'bg-faint')} />
        <span className="text-[13px] font-medium">{tEnum('engine.node', s.node)}</span>
        <span className="font-mono text-[11px] text-faint">{s.node}</span>
        <span className="ml-auto flex items-center gap-1.5 text-[11px] text-muted">
          {tools.length > 0 && <Badge>{tools.length} tool</Badge>}
          {(s.prompt_tokens ?? 0) + (s.completion_tokens ?? 0) > 0 && <span className="num">{(s.prompt_tokens ?? 0) + (s.completion_tokens ?? 0)} ток.</span>}
          <span className="num">{fmtMs(s.latency_ms)}</span>
        </span>
      </button>
      {!open && s.reasoning && <div className="truncate px-10 pb-2 text-xs text-muted">{s.reasoning}</div>}
      {open && (
        <div className="fade-in space-y-2 px-3 pb-3 pl-10">
          {s.reasoning && <p className="text-[13px] leading-relaxed">{s.reasoning}</p>}
          {s.model && (
            <div className="text-xs text-muted">
              {s.model} · {s.prompt_tokens ?? 0}+{s.completion_tokens ?? 0} ток.
            </div>
          )}
          {tools.length > 0 && (
            <div>
              <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-muted">{t('engine.tools')}</div>
              <ul className="space-y-1">
                {tools.map((tc, i) => (
                  <li key={i} className="rounded-lg bg-raised p-2 font-mono text-[11.5px]">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-brand">{tc.name}</span>
                      <span className="text-muted">{fmtMs(tc.ms)}</span>
                    </div>
                    <div className="mt-1 truncate text-muted">{JSON.stringify(tc.args)}</div>
                    {full && tc.result !== undefined && (
                      <details className="mt-1">
                        <summary className="cursor-pointer text-muted">result</summary>
                        <Json value={tc.result} className="mt-1 max-h-64" />
                      </details>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {s.prompt && (
            <details>
              <summary className="cursor-pointer text-xs text-muted">
                {t('engine.prompt')} ({s.prompt.length} симв.)
              </summary>
              <Pre value={s.prompt} className="mt-1 max-h-80" />
            </details>
          )}
          {s.response_raw && (
            <details open={full}>
              <summary className="cursor-pointer text-xs text-muted">{t('engine.response')}</summary>
              <Pre value={s.response_raw} className="mt-1 max-h-80" />
            </details>
          )}
          {full && s.output && Object.keys(s.output).length > 0 && (
            <details>
              <summary className="cursor-pointer text-xs text-muted">{t('engine.output')}</summary>
              <Json value={s.output} className="mt-1 max-h-80" />
            </details>
          )}
          {full && s.input && Object.keys(s.input).length > 0 && (
            <details>
              <summary className="cursor-pointer text-xs text-muted">{t('engine.input')}</summary>
              <Json value={s.input} className="mt-1 max-h-80" />
            </details>
          )}
        </div>
      )}
    </li>
  )
}
