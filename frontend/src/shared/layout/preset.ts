import { create } from 'zustand'
import type { components } from '@/shared/api/types'

/** Только коды пресетов из ТЗ 24.1; заголовок не является авторизацией. */
export const ROLE_CODES = ['cx_operator', 'cx_lead', 'product_manager', 'product_head', 'compliance_officer', 'bank_head', 'admin'] as const
export type ViewRole = typeof ROLE_CODES[number] & components['parameters']['CxRole']
const stored = localStorage.getItem('cx.ui.role')
export const useViewPreset = create<{ role: ViewRole; demonstrator: boolean; setRole: (role: ViewRole) => void; setDemonstrator: (value: boolean) => void }>(set => ({
  role: ROLE_CODES.includes(stored as ViewRole) ? stored as ViewRole : 'cx_lead',
  demonstrator: localStorage.getItem('cx.ui.demonstrator') === 'true',
  setRole: role => { localStorage.setItem('cx.ui.role', role); localStorage.setItem('cx.ui.demonstrator', 'false'); set({ role, demonstrator: false }) },
  setDemonstrator: demonstrator => { localStorage.setItem('cx.ui.demonstrator', String(demonstrator)); set({ demonstrator }) },
}))
