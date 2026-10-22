import type { Config } from 'tailwindcss'

// Токены ТЗ 12.1: primary #21A038, градиент → #0098F8, акцент #F1E813; тёмная/светлая темы через CSS-переменные.
export default {
  darkMode: ['class'],
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'monospace'],
      },
      colors: {
        bg: 'rgb(var(--bg) / <alpha-value>)',
        surface: 'rgb(var(--surface) / <alpha-value>)',
        raised: 'rgb(var(--raised) / <alpha-value>)',
        line: 'rgb(var(--line) / <alpha-value>)',
        ink: 'rgb(var(--ink) / <alpha-value>)',
        muted: 'rgb(var(--muted) / <alpha-value>)',
        faint: 'rgb(var(--faint) / <alpha-value>)',
        brand: { DEFAULT: '#21A038', soft: 'rgb(var(--brand-soft) / <alpha-value>)', sky: '#0098F8', accent: '#F1E813' },
        ok: '#21A038',
        warn: '#E0A800',
        danger: '#D64545',
        info: '#0098F8',
      },
      boxShadow: { card: '0 1px 2px rgb(0 0 0 / 0.06), 0 0 0 1px rgb(var(--line) / 1)' },
      borderRadius: { xl: '14px' },
    },
  },
  plugins: [],
} satisfies Config
