import { GlobalSearch } from '@/shared/components/GlobalSearch'
import { clsx } from 'clsx'
import { Activity, Gauge, MessageSquarePlus, Pause, Play, Square } from 'lucide-react'
import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { NavLink, useNavigate } from 'react-router-dom'
import { LONG_PRESS_MS, useDemoMenu } from './DemoMenu'
import { useSimControl, useSimState } from '@/shared/api/hooks'
import { fmtSim } from '@/shared/lib/format'
import { ThemeSelector } from '@/shared/theme'
import { useWs } from '@/shared/ws/client'
import { Badge } from '@/shared/ui'
import { JuryModal } from './JuryModal'

const SPEEDS = [1, 10, 60, 120, 300]

export function Header() {
  const { t, i18n } = useTranslation()
  const navigate = useNavigate()
  const setDemoOpen = useDemoMenu((s) => s.setOpen)
  const pressTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const longTriggered = useRef(false)
  const q = useSimState()
  const live = useWs((s) => s.sim)
  const wsStatus = useWs((s) => s.status)
  const sim = live ?? q.data ?? null
  const ctl = useSimControl()
  const [jury, setJury] = useState(false)

  const running = !!sim?.running
  const runStatus = sim?.current_run_status ?? null
  const canResume = !running && runStatus === 'paused'

  const clearPress = () => {
    if (pressTimer.current) clearTimeout(pressTimer.current)
    pressTimer.current = null
  }

  const onLogoDown = () => {
    longTriggered.current = false
    clearPress()
    pressTimer.current = setTimeout(() => {
      longTriggered.current = true
      setDemoOpen(true)
    }, LONG_PRESS_MS)
  }

  const onLogoUp = () => {
    clearPress()
    if (!longTriggered.current) navigate('/')
  }

  return (
    <header className="flex min-h-12 shrink-0 flex-wrap items-center gap-x-3 gap-y-2 py-2 border-b border-line bg-surface px-3">
      <div className="flex items-center gap-2">
        <button
          type="button"
          data-testid="app-logo"
          className="grid h-7 w-7 place-items-center rounded-lg bg-brand text-on-brand"
          aria-label={t('app.title')}
          onPointerDown={onLogoDown}
          onPointerUp={onLogoUp}
          onPointerLeave={clearPress}
          onPointerCancel={clearPress}
        >
          <Activity size={16} strokeWidth={2.4} />
        </button>
        <NavLink to="/" className="hidden text-sm font-semibold sm:block">
          {t('app.title')}
        </NavLink>
      </div>

      <nav className="ml-2 flex flex-wrap items-center gap-0.5">
        <Nav to="/" label={t('nav.workspace')} end />
        <Nav to="/finance" label={t('finance.title')} />
        <Nav to="/engine" label={t('nav.engine')} />
        <Nav to="/compliance" label={t('nav.compliance')} />
        <Nav to="/manager" label={t('nav.manager')} />
        <Nav to="/feed" label={t('nav.feed')} />
        <Nav to="/journey" label={t("journeyUi.title")} />
        <Nav to="/trace" label={t("traceUi.title")} />
        <Nav to="/claim" label={t('nav.claim')} />
        <Nav to="/setup" label={t('nav.settings')} />
      </nav>

      <GlobalSearch />
      <div className="mx-auto flex flex-wrap items-center gap-2">
        <div className="flex h-8 items-center gap-2 rounded-lg border border-line bg-raised px-2.5">
          <span className={clsx('h-2 w-2 rounded-full', running ? 'bg-ok animate-pulse' : 'bg-faint')} />
          <span className="text-xs text-muted">{t('sim.clock')}</span>
          <span className="num font-mono text-sm">{fmtSim(sim?.sim_time, 'EEE dd.MM HH:mm')}</span>
          <span className="hidden text-xs text-muted md:inline">
            {sim?.day_no !== undefined && t('sim.day', { n: sim.day_no + 1 })} · {sim?.phase ? t(`sim.phase.${sim.phase}`) : '—'}
          </span>
          {sim && !sim.is_working_day && <Badge tone="warn">{t('sim.weekend')}</Badge>}
          <Badge tone={runStatus === 'running' ? 'ok' : runStatus === 'paused' ? 'warn' : 'neutral'}>{t(`sim.status.${runStatus ?? 'none'}`)}</Badge>
        </div>
        <div className="flex items-center gap-1">
          {running ? (
            <button className="btn btn-sm" onClick={() => ctl.mutate({ action: 'pause' })} disabled={ctl.isPending} title={t('sim.pause')}>
              <Pause size={13} /> {t('sim.pause')}
            </button>
          ) : (
            <button className="btn btn-sm btn-primary" onClick={() => ctl.mutate({ action: canResume ? 'resume' : 'start' })} disabled={ctl.isPending}>
              <Play size={13} /> {canResume ? t('sim.resume') : t('sim.start')}
            </button>
          )}
          <button
            className="btn btn-sm"
            onClick={() => ctl.mutate({ action: 'stop' })}
            disabled={ctl.isPending || !runStatus || runStatus === 'stopped' || runStatus === 'completed'}
            title={t('sim.stop')}
          >
            <Square size={12} />
          </button>
          <div className="ml-1 hidden items-center gap-0.5 rounded-lg border border-line p-0.5 lg:flex" title={t('sim.speed')}>
            <Gauge size={13} className="ml-1 text-muted" />
            {SPEEDS.map((s) => (
              <button
                key={s}
                onClick={() => ctl.mutate({ action: 'set_speed', speed: s })}
                className={clsx(
                  'num h-6 rounded-md px-1.5 text-xs',
                  (sim?.speed ?? 1) === s ? 'bg-brand-soft font-medium text-ink' : 'text-muted hover:bg-raised',
                )}
              >
                {t('sim.speedX', { n: s })}
              </button>
            ))}
          </div>
        </div>
      </div>

      <button className="btn btn-sm" onClick={() => setJury(true)}>
        <MessageSquarePlus size={13} /> {t('common.jury')}
      </button>
      <span className={clsx('flex items-center gap-1 text-xs', wsStatus === 'open' ? 'text-muted' : 'text-danger')} title="WebSocket">
        <span className={clsx('h-1.5 w-1.5 rounded-full', wsStatus === 'open' ? 'bg-ok' : wsStatus === 'connecting' ? 'bg-warn' : 'bg-danger')} />
        {t(`ws.${wsStatus}`)}
      </span>
      <button
        type="button"
        className="btn btn-ghost btn-sm"
        aria-label={t('common.language')}
        onClick={() => void i18n.changeLanguage(i18n.language === 'en' ? 'ru' : 'en')}
      >
        {i18n.language === 'en' ? 'RU' : 'EN'}
      </button>
      <ThemeSelector className="flex max-w-full flex-wrap items-center gap-1" />
      <JuryModal open={jury} onClose={() => setJury(false)} />
    </header>
  )
}

function Nav({ to, label, end }: { to: string; label: string; end?: boolean }) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) =>
        clsx('inline-flex min-h-10 items-center whitespace-nowrap rounded-lg px-2.5 text-sm', isActive ? 'bg-raised font-medium text-ink' : 'text-muted hover:text-ink')
      }
    >
      {label}
    </NavLink>
  )
}
