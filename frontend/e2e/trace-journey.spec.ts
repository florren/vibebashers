import { test, expect } from '@playwright/test'

const event = {
  id: 'EVT-refund-1',
  kind: 'refund',
  phase: 'after',
  ts_sim: '2026-11-09T06:01:00Z',
  ts_real: '2026-10-28T09:01:00Z',
  actor: { kind: 'agent', label_ru: 'Агент' },
  object_ref: { kind: 'ledger', ref: 'LED-000123' },
  title_ru: 'Комиссия возвращена',
  brief_ru: 'Бизнес-правило подтвердило ошибку. Возврат 450 ₽ выполнен.',
  key_facts: [{ label_ru: 'Правило', value_ru: 'RULE-QR-FEE-001', masked: false }],
  badges: { llm_source: 'replay', amount_rub: 450 },
  links: { trace: '/trace/ledger/LED-000123', journey: '/journey/SIG-000123', engine_step: '/engine/1?step=2' },
  importance: 'key',
  run_id: 'SR-0012',
}
const trace = {
  subject: { kind: 'signal', ref: 'SIG-000123', title_ru: 'Лишняя комиссия за QR-оплату', status: 'closed' },
  before: [
    {
      ...event,
      id: 'EVT-fee-1',
      kind: 'fee',
      phase: 'before',
      title_ru: 'Комиссия списана',
      brief_ru: 'Комиссия 450 ₽ стала причиной обращения.',
    },
  ],
  after: [
    event,
    {
      ...event,
      id: 'EVT-notification',
      kind: 'notification',
      title_ru: 'Клиент получил уведомление',
      brief_ru: 'Мы вернули комиссию на ваш счёт.',
    },
  ],
  edges: [],
  groups: [
    {
      kind: 'signal_created',
      count: 118,
      sample_refs: ['SIG-000124', 'SIG-000125', 'SIG-000126'],
      expand_hint_ru: 'Похожие обращения по той же причине',
    },
  ],
  pending: [],
  terminal: { reached: true, outcome_ru: 'Закрыт в срок, комиссия возвращена' },
  stats: { before_count: 1, after_count: 2, build_ms: 14 },
}
const stages = ['intake', 'understanding', 'identity', 'rules', 'decision', 'action', 'execution', 'client_outcome']
const journey = {
  subject: trace.subject,
  stages: stages.map((stage, i) => ({ stage, status: i < 5 ? 'done' : i === 5 ? 'active' : 'pending', events: i === 5 ? [event] : [] })),
  client_lane: [{ channel_code: 'chat', kind: 'final', text_ru: 'Мы вернули комиссию на ваш счёт.', delivered_at: '2026-10-28T09:01:00Z' }],
  summary: { outcome_ru: 'Комиссия возвращена', duration_sim: 'PT60S', amount_rub: 450, llm_source: 'replay' },
}

for (const theme of ['light', 'dark'])
  for (const lang of ['ru', 'en']) {
    test(`trace and journey ${theme} ${lang}`, async ({ page }, testInfo) => {
      const errors: string[] = []
      page.on('pageerror', error => errors.push(error.message))
      await page.addInitScript(
        ({ theme, lang }) => {
          localStorage.setItem('cx.ui.mode', theme)
          localStorage.setItem('cx.lang', lang)
        },
        { theme, lang },
      )
      await page.route(
        (url) => url.pathname.startsWith('/api/'),
        async (route) => {
          const path = new URL(route.request().url()).pathname
          const body = path.startsWith('/api/refs/')
            ? []
            : path.startsWith('/api/trace/')
              ? trace
              : path.startsWith('/api/journey/')
                ? journey
                : path === '/api/search'
                  ? {
                      query: '123',
                      parsed: { mode: 'id', kind: 'number' },
                      hits: [
                        {
                          kind: 'signal',
                          ref: 'SIG-000123',
                          title_ru: 'Комиссия',
                          run_id: 'SR-0012',
                          trace_href: '/trace/signal/SIG-000123',
                        },
                      ],
                      counts_by_kind: { signal: 1 },
                      took_ms: 1,
                    }
                  : path === '/api/sim/state'
                    ? { running: false, current_run_status: 'none', sim_time: '2026-11-09T06:00:00Z', speed: 1 }
                    : {}
          const extra: Record<string, unknown> = {
            '/api/clients': [],
            '/api/scenarios': [],
            '/api/signals/123': { id: 123, client: { id: 1 }, agent_runs: [{ id: 1, kind: 'agent' }], incidents: [{ id: 1 }] },
            '/api/clients/1/360': { id: 1, display_name: 'Клиент демо', clv_estimate_rub: 120000 },
            '/api/agent/graph': { nodes: [{ id: 'act', kind: 'tool' }], edges: [] },
            '/api/agent/runs/1': { id: 1, kind: 'agent', outcome: 'completed', steps: [{ node: 'act', seq: 2, status: 'ok' }] },
            '/api/incidents/1/economics': { potential_loss_rub: 4500, prevented_loss_rub: 4050, formula_ru: 'Серверный расчёт' },
          }
          await route.fulfill({ json: extra[path] ?? body })
        },
      )
      await page.goto('/trace/signal/SIG-000123')
      await expect(page.getByText('Лишняя комиссия за QR-оплату')).toBeVisible()
      await expect(page.getByRole('heading', { name: lang === 'ru' ? 'Итоговое решение' : 'Final decision', exact: false })).toBeVisible()
      await page.screenshot({ path: testInfo.outputPath('trace.png'), fullPage: false })
      await page.getByRole('button', { name: /Комиссия возвращена/ }).click()
      await expect(page.getByRole('dialog')).toBeVisible()
      await page.getByRole('button', { name: lang === 'ru' ? 'Закрыть' : 'Close' }).click()
      await page.keyboard.press('Control+k')
      await page.getByRole('dialog').getByRole('combobox').fill('123')
      await expect(page.getByRole('dialog').getByRole('option')).toBeVisible()
      await page.getByRole('dialog').getByRole('combobox').press('Enter')
      await page.goto('/journey/SIG-000123')
      await expect(page.getByRole('listitem')).toHaveCount(8)
      await expect(page.getByRole('textbox', { name: lang === 'ru' ? 'Сообщение клиента' : 'Customer message', exact: true })).toBeVisible()
      await expect(page.getByText('Мы вернули комиссию на ваш счёт.')).toBeVisible()
      await expect(page.getByRole('group', { name: lang === 'ru' ? 'Граф' : 'Graph', exact: true })).toBeVisible()
      await page.getByRole('button', { name: lang === 'ru' ? /Действия · Завершён/ : /Actions · Completed/ }).click()
      await expect(page.locator('[data-related-step="true"]')).toHaveCount(1)
      await page.getByRole('button', { name: /Комиссия возвращена/ }).click()
      await expect(page.getByRole('group', { name: lang === 'ru' ? 'Граф' : 'Graph', exact: true }).getByRole('button')).toHaveAttribute('aria-pressed', 'true')
      await expect(page.getByText('Комиссия возвращена', { exact: true }).first()).toBeVisible()
      await page.screenshot({ path: testInfo.outputPath('journey.png'), fullPage: false })
      expect(errors).toEqual([])
      await page.setViewportSize({ width: 390, height: 844 })
      await page.goto('/trace/signal/SIG-000123')
      await page.getByRole('tab', { name: lang === 'ru' ? 'ПОСЛЕ' : 'AFTER' }).click()
      await expect(page.getByRole('button', { name: /Комиссия возвращена/ })).toBeVisible()
    })
  }
