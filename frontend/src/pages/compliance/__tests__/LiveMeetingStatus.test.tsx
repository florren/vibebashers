import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { SttMessage } from '@/shared/api/client'
import i18n from '@/shared/i18n'
import { LiveMeeting } from '../LiveMeeting'

const source = vi.hoisted(() => ({ start: vi.fn(), microphone: vi.fn(), nextId: 9 }))
vi.mock('@/shared/api/hooks', () => ({
  useSttProviders: () => ({ data: [{ code: 'vosk', label_ru: 'Vosk', available: true, is_default: true }], isError: false }),
  useComplianceBranches: () => ({ data: [{ id: 1, code: '0042', city_name: 'Учебный город', employees: [{ id: 7, display_name: 'Учебный сотрудник', position: 'Менеджер', is_active: true }] }] }),
  useRefs: () => ({ data: [] }),
  useStartMicSession: () => ({ mutateAsync: source.start, isPending: false }),
}))
vi.mock('@/shared/audio/mic', async original => ({
  ...await original<typeof import('@/shared/audio/mic')>(),
  micSupported: () => true,
  startMic: source.microphone,
}))

class MockWebSocket {
  static OPEN = 1
  static instances: MockWebSocket[] = []
  readyState = MockWebSocket.OPEN
  onopen: (() => unknown) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null
  send = vi.fn()
  close = vi.fn()
  constructor() { MockWebSocket.instances.push(this) }
  receive(message: SttMessage) { this.onmessage?.({ data: JSON.stringify(message) }) }
  disconnect() { this.readyState = 3; this.onclose?.() }
}

const originalScrollTo = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'scrollTo')
beforeEach(async () => {
  await i18n.changeLanguage('en')
  source.nextId = 9
  source.start.mockReset().mockImplementation(async () => {
    const id = source.nextId++
    return { id, public_id: `AS-${String(id).padStart(6, '0')}`, audio_ws_url: `/ws/audio/${id}`, sample_rate: 16000, channels: 1 }
  })
  source.microphone.mockReset().mockResolvedValue({ stop: vi.fn(), level: () => 0 })
  MockWebSocket.instances = []
  vi.stubGlobal('WebSocket', MockWebSocket)
  vi.stubGlobal('isSecureContext', true)
  Object.defineProperty(HTMLElement.prototype, 'scrollTo', { configurable: true, writable: true, value: vi.fn() })
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  if (originalScrollTo) Object.defineProperty(HTMLElement.prototype, 'scrollTo', originalScrollTo)
  else Reflect.deleteProperty(HTMLElement.prototype, 'scrollTo')
})

async function startMeeting() {
  const count = MockWebSocket.instances.length
  fireEvent.click(screen.getByRole('button', { name: i18n.t('live.start') }))
  await waitFor(() => expect(MockWebSocket.instances).toHaveLength(count + 1))
  const socket = MockWebSocket.instances[count]
  if (!socket) throw new Error('Mock WebSocket was not created')
  await act(async () => { await socket.onopen?.() })
  return socket
}

function final(sessionId = 9): SttMessage {
  return {
    type: 'final', session_id: sessionId,
    utterance: { utterance_id: sessionId, seq: 1, speaker: 'employee', speaker_confidence: 1, speaker_source: 'manual', text: 'Синтетическая реплика', t0_ms: 0, t1_ms: 100 },
    session: { trigger_count: 1, status: 'live', alert_threshold: 3 },
  }
}
const closed = (sessionId = 9): SttMessage => ({ type: 'closed', session_id: sessionId, report: { overall_ru: 'Сохранённый отчёт', findings: [] } })
function mount() { return render(<MemoryRouter><LiveMeeting onClose={vi.fn()} /></MemoryRouter>) }

it.each(['ru', 'en'])('shows confirmed server closure after the last live final (%s)', async lang => {
  await i18n.changeLanguage(lang)
  mount()
  const socket = await startMeeting()
  act(() => socket.receive(final()))
  expect(screen.getByText(i18n.t('compliance.sessionStatus.live'), { exact: true })).toBeVisible()
  act(() => socket.receive(closed()))
  expect(screen.getByText(i18n.t('compliance.sessionStatus.closed'), { exact: true })).toBeVisible()
  expect(screen.queryByText(i18n.t('compliance.sessionStatus.live'), { exact: true })).not.toBeInTheDocument()
  expect(screen.getByText(i18n.t('live.triggers', { n: 1, max: 3 }))).toBeVisible()
  expect(screen.getByText('Сохранённый отчёт')).toBeVisible()
})

it.each(['disconnect', 'error'])('does not turn transport %s into confirmed server closure', async event => {
  mount()
  const socket = await startMeeting()
  act(() => socket.receive(final()))
  act(() => { if (event === 'error') socket.onerror?.(); else socket.disconnect() })
  expect(screen.getByText(i18n.t('compliance.sessionStatus.live'), { exact: true })).toBeVisible()
  expect(screen.queryByText(i18n.t('compliance.sessionStatus.closed'), { exact: true })).not.toBeInTheDocument()
  expect(screen.queryByText('Сохранённый отчёт')).not.toBeInTheDocument()
  if (event === 'error') {
    expect(screen.getByText(i18n.t('care.errors.unknown'))).toBeVisible()
    fireEvent.click(screen.getByText(i18n.t('care.details')))
    expect(screen.getByText(i18n.t('live.wsError'))).toBeVisible()
  }
})

it('ignores a closed event belonging to another session', async () => {
  mount()
  const socket = await startMeeting()
  act(() => socket.receive(final()))
  act(() => socket.receive(closed(10)))
  expect(screen.getByText(i18n.t('compliance.sessionStatus.live'), { exact: true })).toBeVisible()
  expect(screen.queryByText('Сохранённый отчёт')).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: i18n.t('live.stop') })).toBeEnabled()
})

it('ignores a late closed event from the previous socket after a new meeting starts', async () => {
  mount()
  const first = await startMeeting()
  act(() => first.receive(final()))
  act(() => first.receive(closed()))
  const current = await startMeeting()
  act(() => current.receive(final(10)))
  act(() => first.receive(closed()))
  expect(screen.getByText(i18n.t('compliance.sessionStatus.live'), { exact: true })).toBeVisible()
  expect(screen.queryByText('Сохранённый отчёт')).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: i18n.t('live.stop') })).toBeEnabled()
})

it('keeps Close disabled while live and permits closing after server confirmation', async () => {
  const onClose = vi.fn()
  render(<MemoryRouter><LiveMeeting onClose={onClose} /></MemoryRouter>)
  const socket = await startMeeting()
  act(() => socket.receive(final()))
  const close = screen.getByRole('button', { name: i18n.t('common.close') })
  expect(close).toBeDisabled()
  fireEvent.click(close)
  expect(onClose).not.toHaveBeenCalled()
  act(() => socket.receive(closed()))
  expect(close).toBeEnabled()
  fireEvent.click(close)
  expect(onClose).toHaveBeenCalledOnce()
})
