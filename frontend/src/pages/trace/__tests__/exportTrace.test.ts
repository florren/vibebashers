import { afterEach, expect, it, vi } from 'vitest'
import i18n from '@/shared/i18n'
import { downloadTrace, traceMarkdown } from '../exportTrace'
import { event, traceFixture } from '../components/__tests__/fixtures'

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals() })

it.each(['ru', 'en'])('Markdown сохраняет стадии/сводки, экранирует текст обращения: %s', lang => {
  const trace = traceFixture(2)
  trace.subject.title_ru = '![image](https://example.invalid/image) <script>test</script>'
  trace.before = [event(3, 'before')]
  trace.pending = [{ kind_ru: 'Ожидаем решения', due_sim: null }]
  trace.stats.truncated_after = true
  const t = i18n.getFixedT(lang)
  const output = traceMarkdown(trace, '12', t)
  const before = output.indexOf(`## ${t('traceUi.before')}`)
  const subject = output.indexOf(`## ${t('traceUi.subject')}`)
  const after = output.indexOf(`## ${t('traceUi.after')}`)
  expect(before).toBeGreaterThan(0)
  expect(subject).toBeGreaterThan(before)
  expect(after).toBeGreaterThan(subject)
  expect(output).toContain('1001')
  expect(output).toContain('Ожидаем решения')
  expect(output).not.toContain('![')
  expect(output).toContain('\\<script\\>')
})

it('JSON скачивается локально с явным scope и освобождением object URL', () => {
  const captured: { parts: BlobPart[]; options?: BlobPropertyBag }[] = []
  vi.stubGlobal('Blob', class { constructor(parts: BlobPart[], options?: BlobPropertyBag) { captured.push({ parts, options }) } })
  const createObjectURL = vi.fn(() => 'blob:synthetic-export')
  const revokeObjectURL = vi.fn()
  vi.stubGlobal('URL', { createObjectURL, revokeObjectURL })
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
    expect(this.download).toBe('trace-INC-000001.json')
  })
  const trace = traceFixture(2)
  downloadTrace(trace, 'all', 'json', i18n.getFixedT('ru'))
  expect(JSON.parse(String(captured[0]!.parts[0]))).toEqual({ export_version: 1, scope: 'all', note: i18n.getFixedT('ru')('traceUi.exportSnapshot'), trace })
  expect(captured[0]!.options?.type).toBe('application/json;charset=utf-8')
  expect(click).toHaveBeenCalledOnce()
  expect(revokeObjectURL).toHaveBeenCalledWith('blob:synthetic-export')
  expect(document.querySelector('a[download]')).toBeNull()
})
