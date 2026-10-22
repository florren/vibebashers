import { defineConfig } from '@playwright/test'

// Дымовые e2e (T-143): нужен работающий стенд (backend с собранным фронтом или vite dev). Адрес — E2E_BASE_URL (по умолчанию :8000).
export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:8000',
    viewport: { width: 1440, height: 900 },
    locale: 'ru-RU',
    screenshot: 'only-on-failure',
  },
})
