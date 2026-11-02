import { useUiTheme } from '@/shared/theming/store'
import { ShellV2 } from './ShellV2'
import { AttentionRuntime } from '@/shared/theming/AttentionRuntime'
import { UndoToast } from '@/shared/components/UndoToast'
import { PriorityStrip } from '@/shared/components/PriorityStrip'
import { NightDigest } from '@/shared/theming/NightDigest'
import { Outlet, useLocation } from 'react-router-dom'
import { useDemoStatus } from '@/shared/api/hooks'
import { DemoMenu } from './DemoMenu'
import { Header } from './Header'

function DemoModeFooter() {
  const q = useDemoStatus()
  const badge = q.data?.badge_ru
  if (q.isError || !badge) return null
  return (
    <footer data-testid="demo-mode-footer" className="shrink-0 border-t border-line px-3 py-1 text-center">
      <span className="text-xs text-muted">{badge}</span>
    </footer>
  )
}

export function Shell() {
  const { pathname, search } = useLocation()
  const explicitScope = new URLSearchParams(search).has('run_id')
  const contained = explicitScope || pathname === '/overview' || pathname === '/cabinet' || pathname.startsWith('/cabinet/')
  const layout = useUiTheme(s => s.layout)
  if (layout === 'v2') return <ShellV2 footer={<DemoModeFooter />} />
  return (
    <div className="app-shell flex h-full min-w-0 flex-col">
      <AttentionRuntime />
      <Header />
      {!contained && <PriorityStrip />}
      {!contained && <NightDigest />}
      <main className="app-content min-h-0 min-w-0 flex-1">
        <Outlet />
      </main>
      <DemoModeFooter />
      <DemoMenu />
      <UndoToast />
    </div>
  )
}
