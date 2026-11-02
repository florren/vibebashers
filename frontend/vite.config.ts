/// <reference types="vitest" />
import react from '@vitejs/plugin-react'
import { defineConfig, transformWithEsbuild } from 'vite'
import { readFileSync } from 'node:fs'
import { fileURLToPath, URL } from 'node:url'

// Dev: прокси /api и /ws на backend (:8000). Prod: dist раздаёт backend (FastAPI StaticFiles) или nginx.
export default defineConfig(({ mode }) => ({
  plugins: [react(), {
    name: 'circadian-bootstrap',
    transformIndexHtml: { order: 'pre', async handler(html) {
      const source = readFileSync(fileURLToPath(new URL('./src/shared/theming/circadian.ts', import.meta.url)), 'utf8').replace(/^export /gm, '')
      const inline = await transformWithEsbuild(`${source}\nbootstrapCircadian()`, 'circadian-bootstrap.ts', { loader: 'ts', format: 'iife', target: 'es2020', minify: true })
      return html.replace('<!-- circadian-bootstrap -->', `<script>${inline.code}</script>`)
    } },
  }],
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  server: {
    port: 5173,
    proxy: {
      '/api': { target: process.env.VITE_API_TARGET ?? 'http://localhost:8000', changeOrigin: true },
      '/ws': { target: (process.env.VITE_API_TARGET ?? 'http://localhost:8000').replace('http', 'ws'), ws: true },
    },
  },
  build: { outDir: mode === 'personal' ? 'dist-personal' : 'dist', sourcemap: false, chunkSizeWarningLimit: 900, ...(mode === 'personal' ? { rollupOptions: { input: 'personal.html' } } : {}) },
  test: { environment: 'jsdom', globals: true, setupFiles: ['./src/test/setup.ts'], css: false, exclude: ['e2e/**', 'node_modules/**', 'dist/**'] },
}))
