import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import i18n from '@/shared/i18n'
import { api } from '@/shared/api/client'
import { useUiTheme } from '@/shared/theming/store'
import { IncidentCard } from '@/pages/workspace/IncidentsBoard'
vi.mock('@/shared/api/client', async original => ({ ...await original<typeof import('@/shared/api/client')>(), api: vi.fn() }))
const clients: QueryClient[] = []
afterEach(async () => { cleanup(); clients.splice(0).forEach(c => c.clear()); await i18n.changeLanguage('ru'); vi.clearAllMocks() })
for (const [lang, zone, label] of [['ru', 'МСК', 'Срок через 3 ч'], ['en', 'MSK', 'Due in 3 h']]) {
  it(`SLA card date and relative hint use the same Moscow business clock: ${lang}`, async () => {
    await i18n.changeLanguage(lang)
    useUiTheme.setState({ simTime: '2026-11-09T06:00:00Z' })
    vi.mocked(api).mockResolvedValue({ sla_warn_hours: 4 })
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } }); clients.push(client)
    render(<QueryClientProvider client={client}><MemoryRouter><IncidentCard i={{ id: 144, public_id: 'INC-000144', title: 'Test incident', status: 'routed', sla_due_sim: '2026-11-09T08:44:00Z' }} teamName={() => 'Team'} /></MemoryRouter></QueryClientProvider>)
    expect(screen.getByText(`09.11 11:44 ${zone}`)).toBeVisible()
    expect(await screen.findByText(label!)).toBeVisible()
    expect(screen.queryByText('09.11 08:44')).not.toBeInTheDocument()
  })
}
