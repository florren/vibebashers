import { useTranslation } from 'react-i18next'
import { BRANCH_STYLE, type BranchCluster } from './branches'
import { directSignalCount, type ClosedSnapshot } from './api'

/** Отдельная группа располагается до signal shapes; ни jitter, ни фиктивных координат. */
export function BranchLayer({ clusters, pixelRatio, zoom, offsetX = 0, closed, selected, onSelect }: { clusters: BranchCluster[]; pixelRatio: number; zoom: number; offsetX?: number; closed: Record<string, ClosedSnapshot> | undefined; selected: string | null; onSelect: (cluster: BranchCluster) => void }) {
  const { t } = useTranslation()
  const unit = 1 / (pixelRatio * zoom)
  return <g data-testid="branch-layer" aria-label={t('branchMap.layer')}>
    {clusters.map(cluster => {
      const { branch, x, y } = cluster.anchor
      const multiple = cluster.items.length > 1
      const style = branch.branch_type ? BRANCH_STYLE[branch.branch_type] : null
      const count = directSignalCount(closed?.[branch.code])
      const label = multiple ? t('branchMap.cluster', { count: cluster.items.length }) : `${branch.code} · ${t('branchMap.type.' + (branch.branch_type ?? 'unknown'))} · ${t('branchMap.status.' + (branch.branch_status ?? 'unknown'))}`
      const quiet = !multiple && branch.branch_status === 'closed' ? count == null ? t('branchMap.closedUnknown') : t('branchMap.closedSignals', { count }) : null
      const activate = () => onSelect(cluster)
      return <g key={cluster.key} data-branch-codes={cluster.items.map(point => point.branch.code).join(" ")} role="button" tabIndex={0} aria-label={quiet ? `${label}; ${quiet}` : label} aria-pressed={!multiple && selected === branch.code} className="cursor-pointer focus-visible:outline-none" transform={`translate(${x} ${y}) scale(${unit})`} onClick={event => { event.stopPropagation(); activate() }} onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); activate() } }}>
        <circle r={22} fill="transparent" />
        <circle r={multiple ? 12 : style?.radius ?? 4} fill={multiple ? 'rgb(var(--surface-2))' : style?.color ?? '#6B7280'} stroke={selected === branch.code ? 'rgb(var(--focus-ring))' : multiple ? 'rgb(var(--ink-muted))' : style?.color ?? '#6B7280'} strokeWidth={multiple || branch.branch_type === 'flagship' ? 2 : 1} strokeDasharray={!multiple ? style?.dash : undefined} opacity={1} />
        {multiple && <text textAnchor="middle" dominantBaseline="central" fontSize={11} fill="rgb(var(--ink))" pointerEvents="none">{cluster.items.length}</text>}
        {quiet && <text x={x * zoom + offsetX > 480 ? -12 : 12} textAnchor={x * zoom + offsetX > 480 ? 'end' : 'start'} y={4} fontSize={10} fill="rgb(var(--ink-muted))" stroke="rgb(var(--surface-1))" strokeWidth={3} paintOrder="stroke" pointerEvents="none">{quiet}</text>}
        <title>{label}{quiet ? `; ${quiet}` : ''}</title>
      </g>
    })}
  </g>
}
