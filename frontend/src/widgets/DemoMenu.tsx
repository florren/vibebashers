import { useNavigate } from 'react-router-dom'
import { loadScenarioJourney } from '@/pages/journey/api'
import { ROUTES } from '@/shared/routes'
import { create } from 'zustand'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useBaselineRestore, useDemoFailover, useDemoPlay, useDemoPrepareScenario, useDemoStatus } from '@/shared/api/hooks'
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
  const nav = useNavigate()
  const [opening, setOpening] = useState(false)
  const open = useDemoMenu((s) => s.open)
  const setOpen = useDemoMenu((s) => s.setOpen)
  const status = useDemoStatus()
  const failover = useDemoFailover()
  const play = useDemoPlay()
  const prepare = useDemoPrepareScenario()
  const preparing = useRef(false)
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

  const prepareScenario = async (id: 'cabinet_red_words_report' | 'csi_and_branches', label: string) => {
    if (preparing.current) return
    preparing.current = true
    try {
      await run(async () => {
        const { run: created } = await prepare.mutateAsync({ id, label })
        if (!created || !Number.isSafeInteger(created.id) || created.id <= 0 || created.kind !== 'scenario' || created.scenario_id !== id) throw new Error(t('demoMenu.invalidRun'))
        nav(id === 'cabinet_red_words_report' ? `/cabinet/deposits?run_id=${created.id}&period=week` : `/csi?run_id=${created.id}&period=month`)
        setOpen(false)
      })
    } finally { preparing.current = false }
  }

  if (!open) return null

  return (
    <div className="fixed inset-0 z-[100] flex items-start justify-center bg-black/40 p-4 sm:pt-14" onClick={() => { if (!prepare.isPending) setOpen(false) }}>
      <div
        role="dialog"
        aria-label={t('demoMenu.title')}
        className="card flex max-h-[calc(100dvh-2rem)] w-full max-w-md flex-col shadow-lg sm:max-h-[calc(100dvh-4.5rem)]"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex shrink-0 items-center justify-between border-b border-line px-3 py-2">
          <h2 className="text-sm font-semibold">{t('demoMenu.title')}</h2>
          <button type="button" className="btn btn-ghost btn-sm" disabled={prepare.isPending} onClick={() => setOpen(false)}>
            {t('demoMenu.close')}
          </button>
        </header>
        <div className="min-h-0 space-y-3 overflow-y-auto p-3">
          {status.isError && <ErrorBox error={status.error} compact />}
          {actionError != null ? <ErrorBox error={actionError} compact /> : null}
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className="btn btn-sm"
              disabled={failover.isPending || prepare.isPending}
              onClick={() => void run(() => failover.mutateAsync({ component: 'llm', to: 'live' }))}
            >
              {t('demoMenu.llmLive')}
            </button>
            <button
              type="button"
              className="btn btn-sm"
              disabled={failover.isPending || prepare.isPending}
              onClick={() => void run(() => failover.mutateAsync({ component: 'llm', to: 'replay' }))}
            >
              {t('demoMenu.llmReplay')}
            </button>
            <button
              type="button"
              className="btn btn-sm"
              disabled={failover.isPending || prepare.isPending}
              onClick={() => void run(() => failover.mutateAsync({ component: 'llm', to: 'mock' }))}
            >
              {t('demoMenu.llmMock')}
            </button>
          </div>
          <div className="flex flex-col gap-2">
            <button className="btn btn-sm justify-start" disabled={prepare.isPending} onClick={() => { nav(ROUTES.journey); setOpen(false) }}>{t('demoMenu.scenario12')}</button>
            <button
              type="button"
              className="btn btn-sm justify-start"
              disabled={play.isPending || prepare.isPending}
              onClick={() =>
                void run(() => play.mutateAsync({ scenario_id: 'qr_fee_public_review', asset_kind: 'post', reset: 'none' }))
              }
            >
              {t('demoMenu.scenario8')}
            </button>
            <button
              type="button"
              className="btn btn-sm justify-start"
              disabled={play.isPending || prepare.isPending}
              onClick={() =>
                void run(() => play.mutateAsync({ scenario_id: 'branch_misselling', asset_kind: 'transcript', reset: 'none' }))
              }
            >
              {t('demoMenu.scenario9')}
            </button>
            <button
              type="button"
              className="btn btn-sm justify-start"
              disabled={play.isPending || prepare.isPending}
              onClick={() =>
                void run(() =>
                  play.mutateAsync({ scenario_id: 'retail_transcript_red_phrases', asset_kind: 'transcript', reset: 'none' }),
                )
              }
            >
              {t('demoMenu.scenario10')}
            </button>
          </div>
          <div className="flex flex-col gap-2">
            <button className="btn btn-sm justify-start" disabled={prepare.isPending} onClick={() => { nav(ROUTES.trace); setOpen(false) }}>{t('demoMenu.scenario13')}</button>
            {([[1, 'deposit_promo_rate'], [8, 'qr_fee_public_review'], [9, 'branch_misselling'], [11, 'social_sarcasm_escalation']] as const).map(([n, scenario]) => <button key={n} className="btn btn-sm justify-start" disabled={opening || prepare.isPending} onClick={() => void run(async () => {
              setOpening(true)
              try { const ref = await loadScenarioJourney(scenario); nav(`${ROUTES.journeyObject(ref)}?mode=presenter`); setOpen(false) }
              finally { setOpening(false) }
            })}>{t('journeyModes.recordedScenario', { n })}</button>)}
            {opening && <p role="status">{t('journeyModes.opening')}</p>}
          </div>
          <div className="flex flex-col gap-2">
            <p className="text-xs text-muted">{t('demoMenu.prepareHint')}</p>
            {([['cabinet_red_words_report', 'prepareCabinet'], ['csi_and_branches', 'prepareCsi']] as const).map(([id, key]) => <button key={id} type="button" className="btn btn-sm demo-menu-prepare justify-start text-left" disabled={prepare.isPending || opening || failover.isPending || play.isPending || baseline.isPending} onClick={() => void prepareScenario(id, t(`demoMenu.${key}`))}>{t(`demoMenu.${key}`)}</button>)}
            {prepare.isPending && <p role="status">{t('demoMenu.preparing')}</p>}
          </div>
          <div>
            <p className="mb-1 text-xs text-muted">{t('theme.appearance')}</p>
            <ThemeSelector className="flex flex-wrap gap-2" />
          </div>
          <button
            type="button"
            className="btn btn-sm w-full"
            disabled={baseline.isPending || prepare.isPending}
            onClick={() => void run(() => baseline.mutateAsync())}
          >
            {t('demoMenu.baselineRestore')}
          </button>
        </div>
      </div>
    </div>
  )
}
