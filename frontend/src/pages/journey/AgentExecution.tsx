import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { GraphView } from '@/pages/engine/GraphView'
import { HitlCard } from '@/pages/workspace/HitlQueue'
import { useAgentGraph, useHitlItem, useRefName } from '@/shared/api/hooks'
import type { AgentRunDetail } from '@/shared/api/client'
import { tEnum } from '@/shared/i18n'
import { nodeStatus, observedEdges, relatedEvents, selectedAttempt, stepFacts, type StepSelection } from './stepSelection'
import type { TraceEvent } from '@/shared/api/trace'
import { ErrorBox } from '@/shared/ui'

export function AgentExecution({
  run,
  current,
  onOpenSignal,
  events,
  selection,
  onSelectStep,
  onFollowCurrent,
}: {
  events: TraceEvent[]
  selection: StepSelection | null
  onSelectStep: (selection: StepSelection) => void
  onFollowCurrent: () => void
  run: AgentRunDetail | undefined
  current: string | null
  onOpenSignal: (id: number) => void
}) {
  const { t } = useTranslation()
  const graph = useAgentGraph()
  const humanId = typeof run?.human_decision?.id === 'number' && run.outcome === 'awaiting_human' ? run.human_decision.id : null
  const human = useHitlItem(humanId)
  const productName = useRefName('products')
  const teamName = useRefName('teams')
  const factText = (fact: ReturnType<typeof stepFacts>[number]) =>
    fact.label === 'product'
      ? fact.value === null
        ? t('journeyLive.unknownProduct')
        : productName(String(fact.value))
      : fact.label === 'team' || fact.label === 'suggestedTeam'
        ? teamName(String(fact.value))
        : fact.label === 'confidence'
          ? `${fact.value}%`
          : fact.label === 'action' || fact.label === 'sentiment'
            ? t(`journeyGraph.${fact.label}.${fact.value}`)
            : String(fact.value)
  const steps = run?.steps ?? []
  const chosen = selectedAttempt(run, selection)
  const chosenNode = selection?.runId === run?.id ? (chosen?.node ?? selection?.node) : undefined
  const associated = run?.id != null ? relatedEvents(events, run.id, chosen) : []
  const taken = observedEdges(steps)
  const base = run?.kind === 'client_twin' ? { version: 'client_twin', nodes: steps.map((s) => ({ id: s.node, kind: 'llm' as const })), edges: [] } : graph.data
  const uniqueNodes = [
    ...new Map(
      [
        ...(base?.nodes ?? []),
        ...steps.filter((s) => !(base?.nodes ?? []).some((n) => n.id === s.node)).map((s) => ({ id: s.node, kind: 'tool' as const })),
      ].map((n) => [n.id, n]),
    ).values(),
  ]
  const actualGraph = {
    ...base,
    nodes: uniqueNodes,
    edges: [
      ...(base?.edges ?? []),
      ...[...taken]
        .filter((edge) => !(base?.edges ?? []).some((e) => `${e.from}>${e.to}` === edge))
        .map((edge) => {
          const [from, to] = edge.split('>')
          return { from, to }
        }),
    ],
  }
  const details = Object.fromEntries(
    uniqueNodes.map((n) => {
      const last = steps.filter((s) => s.node === n.id).at(-1)
      const facts = stepFacts(last)
      return [
        n.id!,
        {
          status: t(`journeyGraph.status.${nodeStatus(run, n.id!, current)}`),
          detail: last?.latency_ms == null ? undefined : `${last.latency_ms} ${t('journeyLive.ms')}`,
          result: facts[0]
            ? `${t(`journeyGraph.fact.${facts[0].label}`)}: ${factText(facts[0])}`
            : t('journeyUi.events', { n: run?.id == null ? 0 : relatedEvents(events, run.id, last).length }),
        },
      ]
    }),
  )
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
        <div className="overflow-x-auto">
          <GraphView
            compact
            graph={actualGraph}
            selectedNode={chosenNode}
            onNodeSelect={
              run?.id == null
                ? undefined
                : (node) => {
                    const last = steps.filter((s) => s.node === node).at(-1)
                    onSelectStep({ runId: run.id!, node, seq: last?.seq })
                  }
            }
            nodeDetails={details}
            takenEdges={taken}
            visited={visited}
            current={current}
            outcome={run?.outcome ?? null}
            failed={new Set(steps.filter((s) => s.status === 'error' && steps.filter((other) => other.node === s.node).at(-1) === s).map((s) => s.node ?? ''))}
          />
        </div>
      )}
      {run?.id != null && <p className="mt-2 text-xs text-muted">{t('journeyGraph.hint')}</p>}
      {chosenNode && run?.id != null && (
        <details
          open
          key={`${run.id}:${chosenNode}:${chosen?.seq ?? ''}`}
          className="mt-3 rounded-xl border border-brand bg-brand-soft p-3"
          aria-label={t('journeyGraph.summary')}
        >
          <summary className="cursor-pointer font-semibold">
            {tEnum('engine.node', chosenNode)} ·{' '}
            {t(
              `journeyGraph.status.${chosen ? (chosen.status === 'error' ? 'error' : chosen.status === 'fallback' ? 'fallback' : chosenNode === 'wait_human' && run.outcome === 'awaiting_human' ? 'waiting_human' : chosenNode === 'followup_monitor' && run.outcome === 'deferred' ? 'scheduled' : 'done') : nodeStatus(run, chosenNode, current)}`,
            )}
          </summary>
          <p className="mt-2 text-sm text-muted">{t(`journeyGraph.intent.${chosenNode}`, { defaultValue: t('journeyGraph.genericIntent') })}</p>
          {steps.filter((s) => s.node === chosenNode).length > 1 && (
            <label className="mt-2 block text-xs">
              {t('journeyGraph.attempt')}{' '}
              <select
                className="input"
                value={chosen?.seq ?? ''}
                onChange={(e) => onSelectStep({ runId: run.id!, node: chosenNode, seq: Number(e.target.value) })}
              >
                {steps
                  .filter((s) => s.node === chosenNode)
                  .map((s) => (
                    <option key={s.seq} value={s.seq}>
                      #{s.seq} · {t(`journeyGraph.status.${s.status === 'error' ? 'error' : s.status === 'fallback' ? 'fallback' : 'done'}`)}
                    </option>
                  ))}
              </select>
            </label>
          )}
          <dl className="my-2 flex flex-wrap gap-x-4 gap-y-1 text-sm">
            {stepFacts(chosen).map((fact) => (
              <div key={fact.label}>
                {t(`journeyGraph.fact.${fact.label}`)}: <strong>{factText(fact)}</strong>
              </div>
            ))}
          </dl>
          {[...new Set(associated.map((e) => e.brief_ru))].slice(0, 3).map((brief) => (
            <p className="my-1 text-sm" key={brief}>
              {brief}
            </p>
          ))}
          <p className="my-2 text-xs text-muted">
            {t('journeyGraph.related', { n: associated.length })}
            {chosen?.latency_ms != null ? ` · ${chosen.latency_ms} ${t('journeyLive.ms')}` : ''}
            {chosen?.model ? ` · ${chosen.model}` : ''}
            {associated.find((e) => e.badges.llm_source)?.badges.llm_source
              ? ` · ${associated.find((e) => e.badges.llm_source)?.badges.llm_source}`
              : chosen?.model?.startsWith('mock')
                ? ' · mock'
                : chosen?.model?.startsWith('replay')
                  ? ' · replay'
                  : ''}
          </p>
          {!associated.length && <p className="text-xs text-muted">{t(chosen ? 'journeyGraph.noLinkedEvents' : 'journeyGraph.noExecution')}</p>}
          <div className="mt-2 flex flex-wrap gap-3 text-xs">
            <button className="btn btn-sm" onClick={onFollowCurrent}>
              {t('journeyGraph.followCurrent')}
            </button>
            {chosen?.seq != null && (
              <Link className="text-brand" to={`/engine/${run.id}?step=${chosen.seq}`}>
                {t('traceUi.engine')}
              </Link>
            )}
          </div>
        </details>
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
