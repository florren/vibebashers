import { useEffect, useState, useSyncExternalStore, type ReactNode } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Header } from './Header'
import { Sidebar } from './Sidebar'
import { SystemStatus } from './SystemStatus'
import { navigationFor } from './Sidebar/navigation'
import { useViewPreset } from '@/shared/layout/preset'
import { useMobileLayout } from '@/shared/layout/device-store'
import { LayoutControl } from '@/shared/layout/LayoutControl'
import { useUndo } from '@/shared/ui/undo'
import { Drawer, Modal } from '@/shared/ui'
import { PriorityStrip } from '@/shared/components/PriorityStrip'
import { UndoToast } from '@/shared/components/UndoToast'
import { AttentionRuntime } from '@/shared/theming/AttentionRuntime'
import { NightDigest } from '@/shared/theming/NightDigest'
import { DemoMenu } from './DemoMenu'

const subscribe = (notify: () => void) => {
  const query = matchMedia('(max-width: 1023px)'); query.addEventListener('change', notify)
  return () => query.removeEventListener('change', notify)
}
export function ShellV2({ footer }: { footer: ReactNode }) {
  const { t } = useTranslation(), navigate = useNavigate(), location = useLocation()
  const narrow = useSyncExternalStore(subscribe, () => matchMedia('(max-width: 1023px)').matches)
  const mobile = useMobileLayout(), small = narrow || mobile
  const { role, demonstrator } = useViewPreset()
  const [navigationOpen, setNavigationOpen] = useState(false), [help, setHelp] = useState(false)
  useEffect(() => { setNavigationOpen(false); useUndo.getState().dismiss() }, [location.key, small])
  useEffect(() => {
    const operations = navigationFor(role, demonstrator).find(group => group.id === 'operations')?.items ?? []
    const handler = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.isComposing || event.altKey || event.ctrlKey || event.metaKey || document.querySelector('[role="dialog"]')) return
      if (event.target instanceof Element && event.target.closest('input,textarea,select,[contenteditable="true"]')) return
      if (event.key === '?') { event.preventDefault(); setHelp(true); return }
      if (/^[1-6]$/.test(event.key)) {
        const item = operations[Number(event.key) - 1]
        if (item) { event.preventDefault(); navigate(item.href) }
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [navigate, role, demonstrator])
  const nav = (close?: () => void) => <><Sidebar onNavigate={close} onHelp={() => setHelp(true)} /><SystemStatus /><div className="p-3"><LayoutControl /></div></>
  return <div className="app-shell shell-v2 flex h-full min-w-0 flex-col" data-layout="v2">
    <AttentionRuntime />
    <Header v2 showSidebarToggle={small} sidebarOpen={navigationOpen} onOpenSidebar={() => setNavigationOpen(true)} navigation={close => nav(close)} />
    <div className="flex min-h-0 min-w-0 flex-1">
      {!small && <aside className="w-64 shrink-0 overflow-y-auto border-r border-line bg-surface">{nav()}</aside>}
      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        <PriorityStrip /><NightDigest />
        <main className="app-content min-h-0 min-w-0 flex-1 overflow-auto"><Outlet /></main>
      </div>
    </div>
    {footer}<DemoMenu /><UndoToast />
    <Drawer open={navigationOpen && !mobile} onClose={() => { setNavigationOpen(false); useUndo.getState().offer(() => setNavigationOpen(true)) }} title={t('shell.navigation')} width="w-[320px]">{nav(() => setNavigationOpen(false))}</Drawer>
    <Modal open={help} onClose={() => setHelp(false)} title={t('shell.shortcuts')}>
      <dl className="space-y-3 text-sm"><div><dt><kbd>1–6</kbd></dt><dd>{t('shell.shortcutOperations')}</dd></div><div><dt><kbd>/</kbd> · <kbd>Ctrl+K</kbd></dt><dd>{t('traceUi.search')}</dd></div><div><dt><kbd>?</kbd></dt><dd>{t('shell.shortcuts')}</dd></div><div><dt><kbd>Esc</kbd></dt><dd>{t('shell.shortcutClose')}</dd></div></dl>
    </Modal>
  </div>
}
