import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import '@/shared/i18n'
import { ApiError } from '@/shared/api/client'
import { ErrorBox, SlaBar } from '@/shared/ui'
import { criticalityTone, incidentStatusTone } from '@/shared/ui/tones'
import { tEnum } from '@/shared/i18n'

describe('ui', () => {
  it('ErrorBox: 501 показывает карточку из Problem', () => {
    render(<ErrorBox error={new ApiError(501, { title: 'Не реализовано', status: 501, card: 'T-093' }, 'x')} />)
    expect(screen.getByText(/T-093/)).toBeInTheDocument()
  })
  it('SlaBar: цвет по остатку', () => {
    const { container, rerender } = render(<SlaBar pct={80} />)
    expect(container.querySelector('.bg-ok')).not.toBeNull()
    rerender(<SlaBar pct={10} />)
    expect(container.querySelector('.bg-danger')).not.toBeNull()
    rerender(<SlaBar pct={90} breached />)
    expect(container.querySelector('.bg-danger')).not.toBeNull()
  })
  it('тона и словарь enum', () => {
    expect(criticalityTone('high')).toBe('danger')
    expect(incidentStatusTone('resolved')).toBe('ok')
    expect(tEnum('signal.type', 'tech_fault')).toBe('Техсбой')
    expect(tEnum('signal.type', 'unknown_code')).toBe('unknown_code')
  })
})
