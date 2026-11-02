import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { VoiceInput } from '@/shared/audio/VoiceInput'
import i18n from '@/shared/i18n'

vi.mock('@/shared/api/hooks', () => ({ useSttProviders: () => ({ data: [{ code: 'vosk', available: true }] }) }))
vi.mock('@/shared/audio/mic', () => ({
  micSupported: () => true,
  startMic: async ({ onFrame }: { onFrame: (pcm: ArrayBuffer) => void }) => {
    onFrame(new ArrayBuffer(32_000))
    return { stop: vi.fn(), level: () => 0, sampleRate: 16_000, channels: 1 }
  },
}))

describe('offline voice input metadata', () => {
  beforeEach(async () => { await i18n.changeLanguage('ru') })

  it('passes the actual server transcript/provider and recorded duration to the claim', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ text: 'Проверьте операцию', provider: 'vosk', latency_ms: 32 }), { status: 200 })))
    const text = vi.fn()
    const voice = vi.fn()
    render(<VoiceInput serverOnly onText={text} onVoice={voice} />)
    fireEvent.click(screen.getByRole('button', { name: 'Надиктовать' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Стоп' }))
    await waitFor(() => expect(voice).toHaveBeenCalledWith({ stt_provider: 'vosk', transcript_raw: 'Проверьте операцию', duration_ms: 1000, latency_ms: 32 }))
    expect(text).toHaveBeenCalledWith('Проверьте операцию')
    expect(fetch).toHaveBeenCalledWith('/api/stt/transcribe?sample_rate=16000', expect.objectContaining({ method: 'POST' }))
  })

  it('does not invent transcript metadata after a failed recognition', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ detail: 'Движок недоступен' }), { status: 503 })))
    const text = vi.fn()
    const voice = vi.fn()
    render(<VoiceInput serverOnly onText={text} onVoice={voice} />)
    fireEvent.click(screen.getByRole('button', { name: 'Надиктовать' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Стоп' }))
    expect(await screen.findByText('Движок недоступен')).toBeVisible()
    expect(text).not.toHaveBeenCalled()
    expect(voice).not.toHaveBeenCalled()
  })
})
