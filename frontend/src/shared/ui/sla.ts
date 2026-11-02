export function slaWarning(due: string | null | undefined, simTime: string | null, status: string | undefined, configured: unknown): number | null {
  if (!due || !simTime || ['closed', 'resolved', 'rejected', 'duplicate'].includes(status ?? '')) return null
  const hours = (Date.parse(due) - Date.parse(simTime)) / 3_600_000
  const warning = typeof configured === 'number' && Number.isFinite(configured) && configured >= 0 ? configured : 4
  return Number.isFinite(hours) && hours <= warning ? hours : null
}

