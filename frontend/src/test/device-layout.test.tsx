import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import '@/shared/i18n'
import { DeviceLayoutRuntime, DeviceSelector } from '@/shared/layout/device'
import { useDeviceMode } from '@/shared/layout/device-store'
import { ResponsiveFilters } from '@/shared/layout/ResponsiveFilters'
import { Modal } from '@/shared/ui'

let narrow = false
let notify: () => void = () => {}
beforeEach(() => {
  narrow = false
  vi.spyOn(window, 'matchMedia').mockImplementation(query => ({ matches: narrow, media: query, onchange: null, addEventListener: (_: string, listener: EventListenerOrEventListenerObject) => { notify = listener as () => void }, removeEventListener: vi.fn(), addListener: vi.fn(), removeListener: vi.fn(), dispatchEvent: () => true }))
  useDeviceMode.getState().setMode('auto')
  document.head.innerHTML = '<meta name="viewport" content="width=device-width, initial-scale=1.0">'
})
afterEach(() => { cleanup(); vi.restoreAllMocks(); localStorage.clear() })

describe('режим устройства', () => {
  it('следует размеру окна в auto, сохраняет выбор и применяет desktop viewport', () => {
    render(<><DeviceLayoutRuntime /><DeviceSelector /></>)
    expect(document.documentElement.dataset.device).toBe('desktop')
    act(() => { narrow = true; notify() })
    expect(document.documentElement.dataset.device).toBe('mobile')
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'desktop' } })
    expect(localStorage.getItem('cx.ui.device_mode')).toBe('desktop')
    expect(document.documentElement.dataset.device).toBe('desktop')
    expect(document.querySelector('meta')?.content).toBe('width=1280')
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'mobile' } })
    expect(document.documentElement.dataset.device).toBe('mobile')
    expect(document.querySelector('meta')?.content).toContain('width=device-width')
  })
  it('при сворачивании фильтров сохраняет введённое значение', async () => {
    useDeviceMode.getState().setMode('mobile')
    const { container } = render(<ResponsiveFilters><input aria-label="Поиск" defaultValue="" /></ResponsiveFilters>)
    const details = container.querySelector('details')!
    expect(details.open).toBe(false)
    fireEvent.click(screen.getByText('Поиск и фильтры'))
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'SIG-000809' } })
    fireEvent.click(screen.getByText('Поиск и фильтры'))
    expect(screen.getByRole('textbox', { hidden: true })).toHaveValue('SIG-000809')
    act(() => useDeviceMode.getState().setMode('desktop'))
    await waitFor(() => expect(details.open).toBe(true))
    expect(screen.getByRole('textbox')).toHaveValue('SIG-000809')
  })
  it('modal удерживает клавиатурный фокус, закрывается Escape и возвращает фокус', async () => {
    const close = vi.fn()
    const trigger = document.createElement('button'); document.body.append(trigger); trigger.focus()
    const { rerender } = render(<Modal open onClose={close} title="Карточка"><button>Последняя</button></Modal>)
    await waitFor(() => expect(document.activeElement?.getAttribute('aria-label')).toBe('Закрыть'))
    const last = screen.getByText('Последняя'); last.focus(); fireEvent.keyDown(document, { key: 'Tab' })
    expect(document.activeElement?.getAttribute('aria-label')).toBe('Закрыть')
    fireEvent.keyDown(document, { key: 'Escape' }); expect(close).toHaveBeenCalledOnce()
    rerender(<Modal open={false} onClose={close} title="Карточка">{null}</Modal>)
    expect(document.activeElement).toBe(trigger); trigger.remove()
    expect(document.body.style.overflow).toBe('')
  })
})
