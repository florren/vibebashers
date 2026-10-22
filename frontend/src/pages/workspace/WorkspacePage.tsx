import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router-dom'
import { useHitlQueue, useSimState } from '@/shared/api/hooks'
import { Empty, Tabs } from '@/shared/ui'
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

type Tab = 'signals' | 'incidents' | 'hitl' | 'deferred' | 'tickets' | 'tasks' | 'map' | 'dashboard' | 'teams' | 'notifications'
const TABS: Tab[] = ['signals', 'incidents', 'hitl', 'tickets', 'deferred', 'map', 'dashboard', 'teams', 'notifications', 'tasks']

/** Экран 1 «Рабочее место» (ТЗ 12.2): KPI-полоса + вкладки. Текущий прогон берём из состояния симулятора. */
export function WorkspacePage() {
  const { t } = useTranslation()
  const [sp, setSp] = useSearchParams()
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
  const hitl = useHitlQueue({ run_id: runId })

  return (
    <div className="flex h-full flex-col">
      <KpiStrip runId={runId} />
      <Tabs
        value={tab}
        onChange={setTab}
        items={TABS.map((id) => ({ id, label: t(`tabs.${id}`), count: id === 'hitl' ? (hitl.data?.items?.length ?? null) : undefined }))}
      />
      <div className="min-h-0 flex-1 overflow-hidden">
        {tab === 'signals' && <SignalsFeed runId={runId} onOpen={setSignalId} />}
        {tab === 'incidents' && <IncidentsBoard runId={runId} />}
        {tab === 'hitl' && <HitlQueue runId={runId} onOpenSignal={setSignalId} />}
        {tab === 'deferred' && <DeferredList runId={runId} onOpenSignal={setSignalId} />}
        {tab === 'map' && <MapTab />}
        {tab === 'dashboard' && <DashboardTab />}
        {tab === 'notifications' && <NotificationsTab runId={runId} />}
        {tab === 'tickets' && <TicketsTab runId={runId} />}
        {tab === 'teams' && <TeamsTab />}
        {tab === 'tasks' && (
          <Empty title={t('common.notImplemented')} hint={t(`placeholder.${tab}`)} />
        )}
      </div>
      <SignalDrawer id={signalId} onClose={() => setSignalId(null)} />
    </div>
  )
}
