import { useEffect, useRef } from 'react'

/** Общий keyboard/focus lifecycle для панели меню, drawer и modal. */
export function useDialogFocus(open: boolean, onClose: () => void) {
  const panel = useRef<HTMLDivElement>(null)
  const close = useRef(onClose)
  useEffect(() => { close.current = onClose }, [onClose])
  useEffect(() => {
    if (!open) return
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const controls = () => [...(panel.current?.querySelectorAll<HTMLElement>('a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex="0"]') ?? [])].filter(el => getComputedStyle(el).display !== 'none')
    const frame = requestAnimationFrame(() => controls()[0]?.focus())
    const key = (event: KeyboardEvent) => {
      const dialogs = document.querySelectorAll('[role="dialog"]')
      if (dialogs[dialogs.length - 1] !== panel.current?.closest('[role="dialog"]') || event.defaultPrevented) return
      if (event.key === 'Escape') { event.preventDefault(); close.current(); return }
      if (event.key !== 'Tab') return
      const elements = controls()
      const first = elements[0], last = elements[elements.length - 1]
      if (!first) { event.preventDefault(); return }
      if (event.shiftKey && (document.activeElement === first || !panel.current?.contains(document.activeElement))) { event.preventDefault(); last?.focus() }
      else if (!event.shiftKey && (document.activeElement === last || !panel.current?.contains(document.activeElement))) { event.preventDefault(); first.focus() }
    }
    document.addEventListener('keydown', key)
    return () => {
      cancelAnimationFrame(frame)
      document.removeEventListener('keydown', key)
      document.body.style.overflow = overflow
      if (previous?.isConnected) previous.focus()
    }
  }, [open])
  return panel
}
