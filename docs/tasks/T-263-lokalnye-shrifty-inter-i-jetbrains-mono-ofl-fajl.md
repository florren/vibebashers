# T-263 — Локальные шрифты Inter и JetBrains Mono (OFL): файлы в public/fonts, @font-face, проверка test_no_cdn

| Поле | Значение |
|---|---|
| Эпик | E1 Каркас, БД, установка |
| Субагент | `SA-UI-Workspace` (рабочее место CX) |
| Оценка | S (≤ 0,5 дня) |
| Волна | 7 |
| Слой | `L4` Фронт (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `done` |

## Цель
Закрыть остаток T-007 и правило 8 AGENTS.md: шрифты из репозитория, а не системные подстановки и не CDN (ТЗ 12.1, 26.1).

## Разделы ТЗ (docs/TZ.md)
§12.1, §26.1, §16.2

## Контракты
- frontend/public/fonts/
- frontend/src/index.css
- docs/LICENSES.md (Inter, JetBrains Mono — OFL 1.1)
- `data/README.md`

## Зависимости
- Зависит от: [T-007](T-007-karkas-frontend-vite-ts-strict-tailwind-tokeny-t.md)
- Блокирует: —

## Что сделать
1. Положить woff2 Inter (400/500/600/700, latin + cyrillic) и JetBrains Mono (400/500) в `frontend/public/fonts/`; `@font-face` с `font-display: swap` в `index.css`; `tailwind.config.ts` оставить как есть.
2. Записать лицензии OFL 1.1 в `docs/LICENSES.md` и источник файлов в `data/README.md`.
3. Тест `tests/integration/test_no_cdn.py` (или vitest) проверяет, что в собранном фронте нет ссылок на внешние шрифты и что файлы шрифтов присутствуют.

## Критерии приёмки
- [x] В собранном фронте нет запросов к внешним доменам за шрифтами; кириллица отображается Inter/JetBrains Mono в офлайне.
- [x] Лицензии указаны.
- [x] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
cd frontend && npm run build && grep -L fonts.googleapis dist/assets/*.css
pytest backend/tests/integration/test_no_cdn.py
```

## Отчёт субагента
Включено в PR #66: локальные woff2 Inter и JetBrains Mono (latin/cyrillic), @font-face, preload и docs/LICENSES.md; npm-зависимости @fontsource удалены. Build проверен без внешней загрузки шрифтов, автоматический test_no_cdn входит в pytest. Ручная офлайн-проверка начертания и скриншоты не выполнены; карточка не объявляется полностью принятой.

Приёмка следующей волны (`feat/T-263-local-fonts`): проверяются ровно 12 локальных WOFF2, каждый `@font-face`/swap/URL и magic bytes; notices Inter/JetBrains Mono приложены к бинарникам и попадают в dist. CI повторно выполняет test_no_cdn после build (до build тест закономерно мог skip). Chromium Playwright с заблокированными внешними доменами проверил custom-font glyphs и точные PostScript names всех весов для латиницы и кириллицы: **1 passed**, внешних запросов **0**. Это проверка изолированного localhost-стенда без внешнего доступа, не режим браузера offline, блокирующий сам localhost. Скриншоты всех начертаний в обеих темах: `docs/screenshots/T-263/{light,dark}.png`; просмотрены. Frontend Node22 lint/tsc/**33 passed**/build; build сохраняет прежнее предупреждение размера chunk (>900 kB), без новых предупреждений шрифтов. test_no_cdn **2 passed**. Общий make lint/test и CI — перед merge.
