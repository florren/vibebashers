import { DeviceLayoutRuntime } from '@/shared/layout/device'
import { EconomicsPage } from '@/pages/finance/EconomicsPage'
import { QueryClient, QueryClientProvider, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { ThemeRuntime } from '@/shared/theming/ThemeRuntime'
import { connectWs } from '@/shared/ws/client'
import { Shell } from '@/widgets/Shell'
import { WorkspacePage } from '@/pages/workspace/WorkspacePage'
import { IncidentPage } from '@/pages/incident/IncidentPage'
import { EnginePage } from '@/pages/engine/EnginePage'
import { CompliancePage } from '@/pages/compliance/CompliancePage'
import { FeedPage } from '@/pages/feed/FeedPage'
import { Client360Page } from '@/pages/client/Client360Page'
import { ClaimPage } from '@/pages/claim/ClaimPage'
import { PublicLayout } from '@/pages/claim/PublicLayout'
import { ManagerPage } from '@/pages/manager/ManagerPage'
import { TracePage } from '@/pages/trace'
import { JourneyPage } from '@/pages/journey'
import { FinancePage } from '@/pages/finance/FinancePage'
import { SetupPage } from '@/pages/setup/SetupPage'

function OperatorRuntime() {
  const qc = useQueryClient()
  useEffect(() => connectWs(qc), [qc])
  return <ThemeRuntime />
}

export function App() {
  const qc = useMemo(() => new QueryClient({ defaultOptions: { queries: { retry: 1, staleTime: 5000, refetchOnWindowFocus: false } } }), [])
  return (
    <QueryClientProvider client={qc}>
      <DeviceLayoutRuntime />
      <BrowserRouter>
        <Routes>
          <Route element={<PublicLayout />}>
            <Route path="claim" element={<ClaimPage />} />
            <Route path="landing" element={<ClaimPage />} />
          </Route>
          <Route element={<><OperatorRuntime /><Shell /></>}>
            <Route index element={<WorkspacePage />} />
            <Route path="clients/:id" element={<Client360Page />} />
            <Route path="incidents/:id" element={<IncidentPage />} />
            <Route path="engine" element={<EnginePage />} />
            <Route path="engine/:runId" element={<EnginePage />} />
            <Route path="compliance" element={<CompliancePage />} />
            <Route path="manager" element={<ManagerPage />} />
            <Route path="feed" element={<FeedPage />} />
            <Route path="trace" element={<TracePage />} />
            <Route path="trace/:kind/:ref" element={<TracePage />} />
            <Route path="journey" element={<JourneyPage />} />
            <Route path="journey/:ref" element={<JourneyPage />} />
            <Route path="economics" element={<EconomicsPage />} />
            <Route path="finance" element={<FinancePage />} />
            <Route path="setup" element={<SetupPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
