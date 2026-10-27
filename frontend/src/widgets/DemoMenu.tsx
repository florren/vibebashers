import { create } from 'zustand'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useBaselineRestore, useDemoFailover, useDemoPlay, useDemoStatus } from '@/shared/api/hooks'
import { ThemeSelector } from '@/shared/theme'
import { ErrorBox } from '@/shared/ui'

export const LONG_PRESS_MS = 600

type DemoMenuStore = {
  open: boolean
  setOpen: (open: boolean) => void
}

export const useDemoMenu = create<DemoMenuStore>((set) => ({
  open: false,
  setOpen: (open) => set({ open }),
}))

export function DemoMenu() {
  const { t } = useTranslation()
  const open = useDemoMenu((s) => s.open)
  const setOpen = useDemoMenu((s) => s.setOpen)
  const status = useDemoStatus()
  const failover = useDemoFailover()
  const play = useDemoPlay()
  const baseline = useBaselineRestore()
  const [actionError, setActionError] = useState<Error | null>(null)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.shiftKey && e.key.toLowerCase() === 'r') {
        e.preventDefault()
        setOpen(true)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [setOpen])

  useEffect(() => {
    if (!open) setActionError(null)
  }, [open])

  const run = async (fn: () => Promise<unknown>) => {
    setActionError(null)
    try {
      await fn()
    } catch (e) {
      setActionError(e instanceof Error ? e : new Error(String(e)))
    }
  }

  if (!open) return null

  return (
    <div className="fixed inset-0 z-[100] flex items-start justify-center bg-black/40 p-4 pt-14" onClick={() => setOpen(false)}>
      <div
        role="dialog"
        aria-label={t('demoMenu.title')}
        className="card w-full max-w-md shadow-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between border-b border-line px-3 py-2">
          <h2 className="text-sm font-semibold">{t('demoMenu.title')}</h2>
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setOpen(false)}>
            {t('demoMenu.close')}
          </button>
        </header>
        <div className="space-y-3 p-3">
          {status.isError && <ErrorBox error={status.error} compact />}
          {actionError != null ? <ErrorBox error={actionError} compact /> : null}
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className="btn btn-sm"
              disabled={failover.isPending}
              onClick={() => void run(() => failover.mutateAsync({ component: 'llm', to: 'live' }))}
            >
              {t('demoMenu.llmLive')}
            </button>
            <button
              type="button"
              className="btn btn-sm"
              disabled={failover.isPending}
              onClick={() => void run(() => failover.mutateAsync({ component: 'llm', to: 'replay' }))}
            >
              {t('demoMenu.llmReplay')}
            </button>
            <button
              type="button"
              className="btn btn-sm"
              disabled={failover.isPending}
              onClick={() => void run(() => failover.mutateAsync({ component: 'llm', to: 'mock' }))}
            >
              {t('demoMenu.llmMock')}
            </button>
          </div>
          <div className="flex flex-col gap-2">
            <button
              type="button"
              className="btn btn-sm justify-start"
              disabled={play.isPending}
              onClick={() =>
                void run(() => play.mutateAsync({ scenario_id: 'qr_fee_public_review', asset_kind: 'post', reset: 'none' }))
              }
            >
              {t('demoMenu.scenario8')}
            </button>
            <button
              type="button"
              className="btn btn-sm justify-start"
              disabled={play.isPending}
              onClick={() =>
                void run(() => play.mutateAsync({ scenario_id: 'branch_misselling', asset_kind: 'transcript', reset: 'none' }))
              }
            >
              {t('demoMenu.scenario9')}
            </button>
            <button
              type="button"
              className="btn btn-sm justify-start"
              disabled={play.isPending}
              onClick={() =>
                void run(() =>
                  play.mutateAsync({ scenario_id: 'retail_transcript_red_phrases', asset_kind: 'transcript', reset: 'none' }),
                )
              }
            >
              {t('demoMenu.scenario10')}
            </button>
          </div>
          <div>
            <p className="mb-1 text-xs text-muted">{t('theme.appearance')}</p>
            <ThemeSelector className="flex flex-wrap gap-2" />
          </div>
          <button
            type="button"
            className="btn btn-sm w-full"
            disabled={baseline.isPending}
            onClick={() => void run(() => baseline.mutateAsync())}
          >
            {t('demoMenu.baselineRestore')}
          </button>
        </div>
      </div>
    </div>
  )
}
