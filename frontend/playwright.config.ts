import { defineConfig } from '@playwright/test'

// Проверенные read-only API и браузерные mocks; новые файлы по умолчанию идут serial.
const readOnlyFiles = ['fonts.spec.ts', 'journey-modes.spec.ts', 'map-layout.spec.ts', 'mobile.spec.ts', 'trace-journey.spec.ts']

// Дымовые e2e (T-143): нужен работающий стенд (backend с собранным фронтом или vite dev). Адрес — E2E_BASE_URL (по умолчанию :8000).
export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  retries: 0,
  workers: 4,
  projects: [
    { name: 'read-only', testMatch: readOnlyFiles, fullyParallel: true },
    { name: 'settings', testIgnore: readOnlyFiles, workers: 1, dependencies: ['read-only'] },
  ],
  reporter: [['list']],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:8000',
    viewport: { width: 1440, height: 900 },
    locale: 'ru-RU',
    screenshot: 'only-on-failure',
  },
})
