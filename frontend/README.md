# CX Pulse Control — фронт (L4)

Vite + React 18 + TypeScript (strict) + Tailwind + TanStack Query + Zustand + react-i18next. Типы API генерируются из `contracts/api/openapi.yaml` (`npm run gen:types`, файл `src/shared/api/types.ts` коммитится; CI проверяет синхрон).

```bash
npm ci
npm run dev        # :5173, прокси /api и /ws → http://localhost:8000 (VITE_API_TARGET переопределяет)
npm run lint && npx tsc --noEmit && npm test -- --run && npm run build
```

Структура `src/`:
- `app/` — роутер и провайдеры; `widgets/` — шапка с управлением симуляцией, KPI-полоса, режим жюри, LogPanel (шаги агента);
- `pages/workspace` — экран 1 (лента сигналов, доска/таблица инцидентов, очередь HITL с accept/modify/reject/delegate, отложенные);
- `pages/incident` — экран 2 (карточка инцидента: сводка, история, сигналы и логи, коммуникации + LogPanel);
- `pages/engine` — экран 3 «Под капотом» (прогоны, шаги с промптами/ответами/инструментами, граф SVG, цепочка решений md/json, живые события WS);
- `shared/api` — fetch-обёртка (Problem+JSON, 501 → «карточка такая-то»), хуки react-query; `shared/ws` — один WebSocket на вкладку с автопереподключением и инвалидацией запросов по топикам; `shared/i18n/ru.json` — все строки интерфейса (проверка `scripts/i18n_check.py`).

Тема: светлая/тёмная (класс `.dark`, CSS-переменные в `index.css`), токены ТЗ 12.1 (`#21A038`, `#0098F8`, `#F1E813`). Шрифты Inter / JetBrains Mono локально (`@fontsource`), без внешних CDN.

Что отложено (см. карточки): карта и KPI-дашборд (B14, ждут `/api/map/*` и `/api/metrics/*`), `/feed` (B16), `/compliance` и `/manager` (B17), e2e Playwright (T-002 — пока скриншотный прогон вручную).
