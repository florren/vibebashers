# T-263 — Локальные шрифты Inter и JetBrains Mono (OFL): файлы в public/fonts, @font-face, проверка test_no_cdn

| Поле | Значение |
|---|---|
| Эпик | E1 Каркас, БД, установка |
| Субагент | `SA-UI-Workspace` (рабочее место CX) |
| Оценка | S (≤ 0,5 дня) |
| Волна | 7 |
| Слой | `L4` Фронт (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `todo` |

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
- [ ] В собранном фронте нет запросов к внешним доменам за шрифтами; кириллица отображается Inter/JetBrains Mono в офлайне.
- [ ] Лицензии указаны.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
cd frontend && npm run build && grep -L fonts.googleapis dist/assets/*.css
pytest backend/tests/integration/test_no_cdn.py
```

## Отчёт субагента
Включено в PR #66: локальные woff2 Inter и JetBrains Mono (latin/cyrillic), @font-face, preload и docs/LICENSES.md; npm-зависимости @fontsource удалены. Build проверен без внешней загрузки шрифтов, автоматический test_no_cdn входит в pytest. Ручная офлайн-проверка начертания и скриншоты не выполнены; карточка не объявляется полностью принятой.
