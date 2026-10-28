import type { ComponentType } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import type { Trace } from '@/shared/api/trace'
import { IdLink } from '@/shared/components/IdLink'
import { ROUTES } from '@/shared/routes'

type DemoKind = 'signal' | 'incident' | 'human_decision' | 'notification' | 'ledger' | 'agent_run'
type Props = { trace: Trace }
const allEvents = (trace: Trace) => [...trace.before, ...trace.after]

function SignalCard({ trace }: Props) {
  return (
    <>
      {allEvents(trace)
        .filter((e) => e.kind === 'source_message')
        .slice(0, 1)
        .map((e) => (
          <p key={e.id}>◉ {e.brief_ru}</p>
        ))}
    </>
  )
}
function IncidentCard({ trace }: Props) {
  return <p>◆ {trace.terminal.outcome_ru}</p>
}
function HumanCard({ trace }: Props) {
  return (
    <>
      {trace.pending.map((p, i) => (
        <p key={i}>◷ {p.kind_ru}</p>
      ))}
    </>
  )
}
function NotificationCard({ trace }: Props) {
  return (
    <>
      {allEvents(trace)
        .filter((e) => e.kind === 'client_reaction')
        .map((e) => (
          <p key={e.id}>✉ {e.brief_ru}</p>
        ))}
    </>
  )
}
function LedgerCard({ trace }: Props) {
  const event = allEvents(trace).find(
    (e) => e.object_ref?.kind === trace.subject.kind && e.object_ref.ref === trace.subject.ref && e.badges.amount_rub != null,
  )
  return event ? (
    <strong>{new Intl.NumberFormat('ru-RU', { style: 'currency', currency: 'RUB' }).format(event.badges.amount_rub!)}</strong>
  ) : null
}
function AgentCard({ trace }: Props) {
  return (
    <>
      {allEvents(trace)
        .filter((e) => e.actor.kind === 'agent')
        .slice(0, 3)
        .map((e) => (
          <p key={e.id}>
            ⚙ {e.title_ru} {e.badges.llm_source}
          </p>
        ))}
    </>
  )
}

const cards: Record<DemoKind, ComponentType<Props>> = {
  signal: SignalCard,
  incident: IncidentCard,
  human_decision: HumanCard,
  notification: NotificationCard,
  ledger: LedgerCard,
  agent_run: AgentCard,
}
function renderer(kind: DemoKind) {
  switch (kind) {
    case 'signal':
    case 'incident':
    case 'human_decision':
    case 'notification':
    case 'ledger':
    case 'agent_run':
      return cards[kind]
    default: {
      const exhaustive: never = kind
      return exhaustive
    }
  }
}
function isDemoKind(kind: string): kind is DemoKind {
  return Object.hasOwn(cards, kind)
}

export function SubjectCard({ trace }: Props) {
  const { t } = useTranslation()
  const Card = isDemoKind(trace.subject.kind) ? renderer(trace.subject.kind) : null
  return (
    <article className="my-3 rounded-xl border-2 border-brand bg-surface p-5 shadow-lg">
      <IdLink kind={trace.subject.kind} value={trace.subject.ref} />
      <h3 className="my-2 text-lg font-semibold">{trace.subject.title_ru}</h3>
      <p>{trace.subject.status}</p>
      {Card && (
        <div className="my-2 text-sm">
          <Card trace={trace} />
        </div>
      )}
      <Link className="text-brand" to={ROUTES.journeyObject(trace.subject.ref)}>
        {t('traceUi.journey')}
      </Link>
    </article>
  )
}
