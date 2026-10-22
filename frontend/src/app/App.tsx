import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useEffect, useMemo } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { applyTheme, useTheme } from '@/shared/theme'
import { connectWs } from '@/shared/ws/client'
import { Shell } from '@/widgets/Shell'
import { WorkspacePage } from '@/pages/workspace/WorkspacePage'
import { IncidentPage } from '@/pages/incident/IncidentPage'
import { EnginePage } from '@/pages/engine/EnginePage'

export function App() {
  const qc = useMemo(() => new QueryClient({ defaultOptions: { queries: { retry: 1, staleTime: 5000, refetchOnWindowFocus: false } } }), [])
  const theme = useTheme((s) => s.theme)
  useEffect(() => applyTheme(theme), [theme])
  useEffect(() => connectWs(qc), [qc])
  return (
    <QueryClientProvider client={qc}>
      <BrowserRouter>
        <Routes>
          <Route element={<Shell />}>
            <Route index element={<WorkspacePage />} />
            <Route path="incidents/:id" element={<IncidentPage />} />
            <Route path="engine" element={<EnginePage />} />
            <Route path="engine/:runId" element={<EnginePage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
