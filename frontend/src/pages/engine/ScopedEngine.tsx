import { useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { api, type Schemas, type DecisionChain } from '@/shared/api/client'
import { useAgentGraph, useAgentRun } from '@/shared/api/hooks'
import { Badge, Empty, ErrorBox, SkeletonRows, Tabs } from '@/shared/ui'
import { tEnum } from '@/shared/i18n'
import { maskBusinessText } from '@/shared/lib/privacy'
import { agentRunStatus } from '@/shared/lib/agentRunStatus'
import { ROUTES } from '@/shared/routes'
import { LogPanel } from '@/widgets/LogPanel'
import { scopedAgentMembership } from './scoped'
import { GraphView } from './GraphView'

/** Scoped drilldown: детали запрашиваются только после server-scoped membership proof. */
export function ScopedEngine({ runScope }: { runScope: string }) {
  const { t } = useTranslation(), { runId: ref } = useParams(), [, setParams] = useSearchParams()
  const id = ref && /^[1-9][0-9]*$/.test(ref) && Number.isSafeInteger(Number(ref)) ? Number(ref) : null
  const [tab, setTab] = useState<'steps'|'graph'|'chain'>('steps')
  const list = useQuery({queryKey:['agent','scoped-list',runScope],queryFn:({signal})=>api<Schemas['AgentRunList']>('/api/agent/runs',{query:{run_id:runScope,kind:'agent',limit:100},signal})})
  const membership = useQuery({queryKey:['agent','scoped-membership',runScope,id],queryFn:({signal})=>scopedAgentMembership(id!,runScope,signal),enabled:id!==null})
  const allowed = id !== null && membership.isSuccess && membership.data === true
  const safeId = allowed ? id : null
  const run = useAgentRun(safeId), graph = useAgentGraph()
  const chain = useQuery({queryKey:['agent','chain',safeId,runScope],queryFn:({signal})=>api<DecisionChain>(`/api/agent/runs/${safeId}/decision-chain`,{query:{format:'json'},signal}),enabled:safeId!==null})
  const suffix = `run_id=${encodeURIComponent(runScope)}`
  return <div className="flex h-full min-w-0 flex-col overflow-auto p-3 md:flex-row" data-scoped-engine>
    <aside className="w-full shrink-0 space-y-3 border-b border-line p-3 md:w-72 md:overflow-auto md:border-b-0 md:border-r">
      <h1 className="font-semibold">{t('nav.engine')}</h1>
      <label className="block text-sm">{t('overviewUi.scope')}<select className="input mt-1 w-full" value={runScope} onChange={event=>setParams(previous=>{const next=new URLSearchParams(previous);next.set('run_id',event.target.value);return next})}><option value={runScope}>{t('overviewUi.selectedRun',{run:runScope})}</option>{runScope!=='all'&&<option value="all">{t('overviewUi.all')}</option>}{runScope!=='current'&&<option value="current">{t('overviewUi.current')}</option>}</select></label>
      <Link className="text-sm text-brand underline" to="/engine">{t('overviewUi.globalTools')}</Link>
      {list.isError?<ErrorBox error={list.error}/>:list.isPending?<SkeletonRows n={3}/>:<ul className="space-y-2">{list.data.items?.map(row=><li key={row.id}><Link className="block rounded border border-line p-2 text-sm text-brand" aria-current={row.id===id?'page':undefined} to={`/engine/${row.id}?${suffix}`}>#{row.id} · {tEnum('engine.outcome',row.outcome)}</Link></li>)}</ul>}
    </aside>
    <div className="min-w-0 flex-1 space-y-3 p-3">
      {membership.isError?<ErrorBox error={membership.error}/>:id===null?<Empty title={t('engine.selectRun')}/>:membership.isPending?<SkeletonRows n={3}/>:!allowed?<Empty title={t('overviewUi.agentOutsideScope')}/>:<>
        {run.data?.signal_id!=null&&<div className="flex flex-wrap gap-2"><Link className="btn btn-sm" to={`${ROUTES.journeyObject(String(run.data.signal_id))}?${suffix}`}>{t('overviewUi.journey')}</Link><Link className="btn btn-sm" to={`${ROUTES.traceObject('signal',String(run.data.signal_id))}?${suffix}`}>{t('overviewUi.trace')}</Link></div>}
        <Tabs value={tab} onChange={setTab} items={[{id:'steps',label:t('engine.steps')},{id:'graph',label:t('engine.graph')},{id:'chain',label:t('engine.chain')}]}/>
        {tab==='steps'&&<LogPanel runId={safeId} full/>}
        {tab==='graph'&&(graph.isError?<ErrorBox error={graph.error}/>:graph.data?<GraphView graph={graph.data} visited={new Set(run.data?.steps?.map(step=>step.node??''))} current={run.data?.current_node??null} outcome={run.data?.outcome??null} executionStatus={agentRunStatus(run.data)}/>:<SkeletonRows n={3}/>)}
        {tab==='chain'&&(chain.isError?<ErrorBox error={chain.error}/>:chain.isPending?<SkeletonRows n={3}/>:<><Badge>{chain.data.llm_source??t('overviewUi.unknownMode')}</Badge><ol className="space-y-3">{chain.data.steps.map(step=><li className="border-l-2 border-line pl-3" key={step.step}><strong>{step.step}. {tEnum('engine.node',step.node)}</strong><p>{maskBusinessText(step.why_ru)}</p></li>)}</ol></>)}
      </>}
    </div>
  </div>
}
