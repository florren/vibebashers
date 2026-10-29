import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { GraphView } from '@/pages/engine/GraphView'
import { HitlCard } from '@/pages/workspace/HitlQueue'
import { useAgentGraph, useHitlItem } from '@/shared/api/hooks'
import type { AgentRunDetail } from '@/shared/api/client'
import { tEnum } from '@/shared/i18n'
import { ErrorBox } from '@/shared/ui'

export function AgentExecution({
  run,
  current,
  onOpenSignal,
}: {
  run: AgentRunDetail | undefined
  current: string | null
  onOpenSignal: (id: number) => void
}) {
  const { t } = useTranslation()
  const graph = useAgentGraph()
  const humanId = typeof run?.human_decision?.id === 'number' && run.outcome === 'awaiting_human' ? run.human_decision.id : null
  const human = useHitlItem(humanId)
  const steps = run?.steps ?? []
  const visited = new Set(steps.filter((s) => s.status !== 'error').map((s) => s.node ?? ''))
  return (
    <section className="card p-4" aria-label={t('journeyLive.graph')}>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-semibold">{t('journeyLive.graph')}</h2>
        {run?.id && (
          <Link className="text-xs text-brand" to={`/engine/${run.id}`}>
            {t('traceUi.engine')} · #{run.id}
          </Link>
        )}
      </div>
      {!run && (
        <p className="text-sm text-muted" role="status">
          {t('journeyLive.noRun')}
        </p>
      )}
      {run && (
        <p className="mb-3 text-sm" role="status">
          {t('journeyLive.execution')}: {t(`engine.outcome.${run.outcome ?? 'running'}`)}
        </p>
      )}
      {graph.isError && <ErrorBox error={graph.error} compact />}
      {graph.data && (
        <GraphView
          compact
          graph={
            run?.kind === 'client_twin'
              ? { version: 'client_twin', nodes: steps.map((s) => ({ id: s.node, kind: 'llm' as const })), edges: [] }
              : graph.data
          }
          visited={visited}
          current={current}
          outcome={run?.outcome ?? null}
          failed={new Set(steps.filter((s) => s.status === 'error').map((s) => s.node ?? ''))}
        />
      )}
      {steps.some((s) => s.model) && (
        <ul className="mt-3 flex flex-wrap gap-2 text-xs" aria-label={t('journeyLive.models')}>
          {steps
            .filter((s) => s.model)
            .map((s) => (
              <li className="rounded border border-line px-2 py-1" key={s.seq}>
                {tEnum('engine.node', s.node)} · {s.model}
                {s.status === 'fallback' ? ` · ${t('journeyLive.fallback')}` : ''} · {s.latency_ms ?? 0} {t('journeyLive.ms')}
              </li>
            ))}
        </ul>
      )}
      {human.isError && <ErrorBox error={human.error} compact />}
      {human.data && (
        <details className="mt-3 rounded-xl border border-warn p-2">
          <summary>{t('journeyLive.humanDecision')}</summary>
          <HitlCard item={human.data} onOpenSignal={onOpenSignal} />
        </details>
      )}
    </section>
  )
}
