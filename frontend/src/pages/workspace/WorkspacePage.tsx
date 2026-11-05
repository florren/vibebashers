import { useUndo } from '@/shared/ui/undo'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, Navigate, useSearchParams } from 'react-router-dom'
import { useHitlQueue, useSimState } from '@/shared/api/hooks'
import { ScopedRunBoundary } from '@/shared/layout/ScopedRunBoundary'
import { ScopedMetrics } from '@/pages/overview/ScopedMetrics'
import { Tabs } from '@/shared/ui'
import { useWs } from '@/shared/ws/client'
import { KpiStrip } from '@/widgets/KpiStrip'
import { SignalsFeed } from './SignalsFeed'
import { SignalDrawer } from './SignalDrawer'
import { IncidentsBoard } from './IncidentsBoard'
import { HitlQueue } from './HitlQueue'
import { DeferredList } from './DeferredList'
import { DashboardTab } from './DashboardTab'
import { MapTab } from './MapTab'
import { NotificationsTab } from './NotificationsTab'
import { TicketsTab } from './TicketsTab'
import { TeamsTab } from './TeamsTab'
import { TasksTab } from './TasksTab'

type Tab = 'signals' | 'incidents' | 'hitl' | 'deferred' | 'tickets' | 'tasks' | 'map' | 'dashboard' | 'teams' | 'notifications'
const TABS: Tab[] = ['signals', 'incidents', 'hitl', 'tickets', 'deferred', 'map', 'dashboard', 'teams', 'notifications', 'tasks']

/** Экран 1 «Рабочее место» (ТЗ 12.2): KPI-полоса + вкладки. Текущий прогон берём из состояния симулятора. */
export function WorkspacePage() {
  const [params] = useSearchParams()
  // Scope карты фиксируем до монтирования legacy KPI и любых дочерних запросов.
  if (params.get('tab') === 'map' && !params.has('run_id')) {
    const scoped = new URLSearchParams(params); scoped.set('run_id', 'current')
    return <Navigate replace to={{ search: scoped.toString() }} />
  }
  const requested = params.get('run_id')
  return requested === null ? <WorkspaceContent /> : <ScopedRunBoundary requested={requested}>{resolved => <WorkspaceContent key={resolved} resolvedScope={resolved} />}</ScopedRunBoundary>
}

function WorkspaceContent({ resolvedScope }: { resolvedScope?: string }) {
  const { t } = useTranslation()
  const [sp, setSp] = useSearchParams()
  const incomingScope = resolvedScope
  const setRunScope = (value: string) => setSp(previous => { const next = new URLSearchParams(previous); next.set('run_id', value); return next }, { replace: true })
  const tab = (sp.get('tab') as Tab | null) ?? 'signals'
  const setTab = (v: Tab) =>
    setSp(
      (p) => {
        p.set('tab', v)
        return p
      },
      { replace: true },
    )
  const [signalId, setSignalId] = useState<number | null>(null)

  const live = useWs((s) => s.sim)
  const simQ = useSimState()
  const runId = (live ?? simQ.data)?.current_run_id ?? undefined
  const dataRunId = incomingScope ?? runId
  const hitl = useHitlQueue({ run_id: incomingScope ?? 'all' })

  return (
    <div className="workspace-page flex h-full min-w-0 flex-col">
      {incomingScope === undefined && <KpiStrip runId={runId} />}
      {incomingScope !== undefined && <div className="flex flex-wrap gap-3 border-b border-line px-3 py-2 text-sm" role="status"><span>{t('overviewUi.selectedRun', { run: incomingScope === 'all' ? t('overviewUi.all') : '#' + incomingScope })}</span><Link className="text-brand underline" to={`/overview?run_id=${encodeURIComponent(incomingScope)}`}>{t('overviewUi.title')}</Link></div>}
      <Tabs
        value={tab}
        onChange={setTab}
        items={TABS.map((id) => ({ id, label: t(`tabs.${id}`), count: id === 'hitl' ? (hitl.data?.total ?? hitl.data?.items?.length ?? null) : undefined }))}
      />
      <div className="workspace-body min-h-0 min-w-0 flex-1 overflow-hidden">
        {tab === 'signals' && <SignalsFeed runId={runId} onOpen={setSignalId} runScope={incomingScope} onRunScopeChange={setRunScope} />}
        {tab === 'incidents' && <IncidentsBoard runId={dataRunId} />}
        {tab === 'hitl' && <HitlQueue runId={runId} onOpenSignal={setSignalId} runScope={incomingScope} onRunScopeChange={setRunScope} />}
        {tab === 'deferred' && <DeferredList runId={dataRunId} onOpenSignal={setSignalId} />}
        {tab === 'map' && <MapTab runScope={incomingScope} onRunScopeChange={setRunScope} />}
        {tab === 'dashboard' && (incomingScope === undefined ? <DashboardTab runId={runId} /> : <ScopedMetrics run={incomingScope} />)}
        {tab === 'notifications' && <NotificationsTab runId={dataRunId} />}
        {tab === 'tickets' && <TicketsTab runId={dataRunId} />}
        {tab === 'teams' && <TeamsTab runScope={incomingScope} />}
        {tab === 'tasks' && <TasksTab runId={dataRunId} />}
      </div>
      <SignalDrawer id={signalId} onClose={() => { const previous = signalId; setSignalId(null); useUndo.getState().offer(() => setSignalId(previous)) }} />
    </div>
  )
}
