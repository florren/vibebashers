import { clsx } from 'clsx'
import { Columns3, Table2 } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import type { IncidentBrief } from '@/shared/api/client'
import { useIncidents, useRefName } from '@/shared/api/hooks'
import { tEnum } from '@/shared/i18n'
import { fmtSim } from '@/shared/lib/format'
import { Badge, Empty, ErrorBox, SkeletonRows, SlaBar } from '@/shared/ui'
import { criticalityTone, incidentStatusTone } from '@/shared/ui/tones'

const COLUMNS: { id: string; statuses: string[] }[] = [
  { id: 'new', statuses: ['new', 'classified'] },
  { id: 'routed', statuses: ['routed'] },
  { id: 'in_progress', statuses: ['in_progress', 'fix_proposed', 'fix_deployed'] },
  { id: 'waiting', statuses: ['awaiting_human', 'awaiting_client', 'verifying'] },
  { id: 'escalated', statuses: ['escalated'] },
  { id: 'done', statuses: ['resolved', 'closed'] },
]
const COL_LABEL: Record<string, string> = {
  new: 'Новые',
  routed: 'Направлены',
  in_progress: 'В работе',
  waiting: 'Ожидание',
  escalated: 'Эскалация',
  done: 'Решены',
}

export function IncidentsBoard({ runId }: { runId: number | undefined }) {
  const { t } = useTranslation()
  const [mode, setMode] = useState<'board' | 'table'>('board')
  const [team, setTeam] = useState('')
  const [slaRisk, setSlaRisk] = useState<'' | 'warning' | 'breached'>('')
  const query = useMemo(
    () => ({ run_id: runId, team: team || undefined, sla_risk: slaRisk || undefined, sort: 'priority', limit: 200 }),
    [runId, team, slaRisk],
  )
  const list = useIncidents(query)
  const teamName = useRefName('teams')
  const items = useMemo(() => list.data?.items ?? [], [list.data])
  const teams = useMemo(() => Array.from(new Set(items.map((i) => i.team_code).filter(Boolean))) as string[], [items])

  return (
    <div className="flex h-full flex-col">
      <div className="flex h-10 shrink-0 items-center gap-2 border-b border-line px-3">
        <div className="flex rounded-lg border border-line p-0.5">
          <button
            className={clsx('flex h-6 items-center gap-1 rounded-md px-2 text-xs', mode === 'board' ? 'bg-raised font-medium' : 'text-muted')}
            onClick={() => setMode('board')}
          >
            <Columns3 size={12} /> {t('common.board')}
          </button>
          <button
            className={clsx('flex h-6 items-center gap-1 rounded-md px-2 text-xs', mode === 'table' ? 'bg-raised font-medium' : 'text-muted')}
            onClick={() => setMode('table')}
          >
            <Table2 size={12} /> {t('common.table')}
          </button>
        </div>
        <select className="input h-7 text-xs" value={team} onChange={(e) => setTeam(e.target.value)}>
          <option value="">
            {t('common.team')}: {t('common.all')}
          </option>
          {teams.map((c) => (
            <option key={c} value={c}>
              {teamName(c)}
            </option>
          ))}
        </select>
        <select className="input h-7 text-xs" value={slaRisk} onChange={(e) => setSlaRisk(e.target.value as typeof slaRisk)}>
          <option value="">
            {t('common.sla')}: {t('common.all')}
          </option>
          <option value="warning">под угрозой</option>
          <option value="breached">просрочен</option>
        </select>
        <span className="ml-auto text-xs text-muted">{t('common.items', { n: items.length })}</span>
      </div>
      {list.isPending && <SkeletonRows />}
      {list.isError && <ErrorBox error={list.error} />}
      {list.data && items.length === 0 && <Empty title={t('common.empty')} />}
      {list.data && items.length > 0 && (mode === 'board' ? <Board items={items} teamName={teamName} /> : <Table items={items} teamName={teamName} />)}
    </div>
  )
}

function Board({ items, teamName }: { items: IncidentBrief[]; teamName: (c?: string | null) => string }) {
  return (
    <div className="flex min-h-0 flex-1 gap-2 overflow-x-auto p-3">
      {COLUMNS.map((col) => {
        const rows = items.filter((i) => col.statuses.includes(i.status ?? ''))
        return (
          <div key={col.id} className="flex w-64 shrink-0 flex-col rounded-xl bg-raised/60">
            <div className="flex h-8 items-center gap-2 px-3 text-xs font-semibold text-muted">
              {COL_LABEL[col.id]} <span className="num rounded-full bg-surface px-1.5 text-[11px]">{rows.length}</span>
            </div>
            <div className="min-h-0 flex-1 space-y-2 overflow-y-auto px-2 pb-2">
              {rows.map((i) => (
                <IncidentCard key={i.id} i={i} teamName={teamName} />
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )
}

export function IncidentCard({ i, teamName }: { i: IncidentBrief; teamName: (c?: string | null) => string }) {
  return (
    <Link to={`/incidents/${i.id}`} className="card block p-2.5 transition hover:ring-1 hover:ring-brand/40">
      <div className="mb-1 flex items-center gap-1.5">
        <span className="num font-mono text-[11px] text-muted">{i.public_id}</span>
        <Badge tone={criticalityTone(i.criticality)}>P{i.priority}</Badge>
        {(i.mass_impact ?? 0) > 1 && <Badge tone="warn">{i.mass_impact} кл.</Badge>}
        {i.routing_status === 'escalated' && <Badge tone="danger">эскалация</Badge>}
        <span className="ml-auto text-[11px] text-muted">{tEnum('incident.complexity', i.complexity)}</span>
      </div>
      <div className="line-clamp-2 text-[13px] leading-snug">{i.title}</div>
      <div className="mt-1.5 flex items-center gap-2 text-[11px] text-muted">
        <span className="truncate">{teamName(i.team_code)}</span>
        <span className="ml-auto num font-mono">{fmtSim(i.sla_due_sim)}</span>
      </div>
      <SlaBar className="mt-1.5" pct={i.sla_remaining_pct} breached={i.sla_breached} />
    </Link>
  )
}

function Table({ items, teamName }: { items: IncidentBrief[]; teamName: (c?: string | null) => string }) {
  return (
    <div className="min-h-0 flex-1 overflow-auto">
      <table className="w-full text-[13px]">
        <thead className="sticky top-0 bg-surface text-left text-[11px] uppercase tracking-wide text-muted">
          <tr className="border-b border-line">
            <th className="px-3 py-2 font-medium">ID</th>
            <th className="px-2 py-2 font-medium">Инцидент</th>
            <th className="px-2 py-2 font-medium">Статус</th>
            <th className="px-2 py-2 font-medium">P</th>
            <th className="px-2 py-2 font-medium">Команда</th>
            <th className="px-2 py-2 font-medium">Создан</th>
            <th className="px-2 py-2 font-medium">SLA</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {items.map((i) => (
            <tr key={i.id} className="hover:bg-raised">
              <td className="px-3 py-1.5 font-mono text-xs text-muted">
                <Link to={`/incidents/${i.id}`} className="hover:text-brand">
                  {i.public_id}
                </Link>
              </td>
              <td className="max-w-[420px] truncate px-2 py-1.5">
                <Link to={`/incidents/${i.id}`}>{i.title}</Link>
              </td>
              <td className="px-2 py-1.5">
                <Badge tone={incidentStatusTone(i.status)}>{tEnum('incident.status', i.status)}</Badge>
              </td>
              <td className="px-2 py-1.5">
                <Badge tone={criticalityTone(i.criticality)}>P{i.priority}</Badge>
              </td>
              <td className="px-2 py-1.5 text-muted">{teamName(i.team_code)}</td>
              <td className="num px-2 py-1.5 font-mono text-xs text-muted">{fmtSim(i.created_sim)}</td>
              <td className="w-36 px-2 py-1.5">
                <div className="flex items-center gap-2">
                  <SlaBar pct={i.sla_remaining_pct} breached={i.sla_breached} className="w-20" />
                  <span className="num font-mono text-[11px] text-muted">{i.sla_breached ? 'срыв' : `${Math.round(i.sla_remaining_pct ?? 0)}%`}</span>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
