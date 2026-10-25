import { Outlet } from 'react-router-dom'
import { useDemoStatus } from '@/shared/api/hooks'
import { DemoMenu } from './DemoMenu'
import { Header } from './Header'

function DemoModeFooter() {
  const q = useDemoStatus()
  const badge = q.data?.badge_ru
  if (q.isError || !badge) return null
  return (
    <footer data-testid="demo-mode-footer" className="shrink-0 border-t border-line px-3 py-1 text-center">
      <span className="text-[11px] text-muted">{badge}</span>
    </footer>
  )
}

export function Shell() {
  return (
    <div className="flex h-full flex-col">
      <Header />
      <main className="min-h-0 flex-1">
        <Outlet />
      </main>
      <DemoModeFooter />
      <DemoMenu />
    </div>
  )
}
