import type { ViewRole } from '@/shared/layout/preset'

export type NavItem = { id: string; label: string; href: string }
export type NavGroup = { id: string; items: NavItem[] }
const GROUPS: NavGroup[] = [
  { id: 'operations', items: [
    { id: 'overview', label: 'shell.overview', href: '/overview' },
    { id: 'signals', label: 'tabs.signals', href: '/workspace?tab=signals' },
    { id: 'incidents', label: 'tabs.incidents', href: '/workspace?tab=incidents' },
    { id: 'hitl', label: 'tabs.hitl', href: '/workspace?tab=hitl' },
    { id: 'map', label: 'tabs.map', href: '/workspace?tab=map' },
    { id: 'zones', label: 'shell.zones', href: '/workspace?tab=map&map_mode=zones' },
  ] },
  { id: 'audit', items: [
    { id: 'engine', label: 'nav.engine', href: '/engine' },
    { id: 'compliance', label: 'nav.compliance', href: '/compliance' },
    { id: 'manager', label: 'nav.manager', href: '/manager' },
  ] },
  { id: 'demonstration', items: [
    { id: 'journey', label: 'journeyUi.title', href: '/journey' },
    { id: 'trace', label: 'shell.searchTrace', href: '/trace' },
    { id: 'feed', label: 'nav.feed', href: '/feed' },
  ] },
  { id: 'product', items: [
    { id: 'cabinet', label: 'shell.cabinet', href: '/cabinet' },
    { id: 'csi', label: 'shell.csi', href: '/csi' },
    { id: 'economics', label: 'shell.economics', href: '/economics' },
  ] },
]
/** Скрываем нерелевантные пункты пресета; прямые адреса доступны, это не RBAC. */
export function navigationFor(role: ViewRole, demonstrator = false): NavGroup[] {
  if (demonstrator || role === 'cx_lead' || role === 'admin') return GROUPS
  return GROUPS.flatMap(group => {
    if (role === 'cx_operator' && (group.id === 'product' || group.id === 'audit')) return []
    if (['product_manager', 'product_head', 'bank_head'].includes(role) && group.id === 'audit') return []
    let items = group.items
    if (['product_manager', 'product_head', 'bank_head'].includes(role) && group.id === 'operations') items = items.filter(item => ['overview', 'map', 'zones'].includes(item.id))
    if (role !== 'cx_operator' && group.id === 'demonstration') items = items.filter(item => item.id !== 'feed')
    return [{ ...group, items }]
  })
}
export function itemActive(item: NavItem, pathname: string, search: string): boolean {
  const url = new URL(item.href, 'http://localhost')
  if (url.pathname !== pathname) return false
  const actual = new URLSearchParams(search)
  if (item.id === 'map' && actual.get('map_mode') === 'zones') return false
  return [...url.searchParams].every(([key, value]) => actual.get(key) === value)
}
