# T-007 — Каркас frontend: Vite, TS strict, Tailwind-токены, темы, шрифты, роутинг, i18n-скелет

| Поле | Значение |
|---|---|
| Эпик | E1 Каркас, БД, установка |
| Субагент | `SA-UI-Workspace` (рабочее место CX) |
| Оценка | M (1–2 дня) |
| Волна | 1 |
| Слой | `L4` Фронт (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `todo` |

## Цель
Единая визуальная база в стиле ТЗ 12.1 для всех экранов.

## Разделы ТЗ (docs/TZ.md)
§12.1, §12.4

## Контракты
- AGENTS.md §6.5

## Зависимости
- Зависит от: [T-001](T-001-skelet-repozitoriya-makefile-env-example-pre-com.md)
- Блокирует: [T-010](T-010-ui-mastera-nastrojki-9-shagov-i-ekran-nastrojki.md), [T-086](T-086-layout-rabochego-mesta-cx-shapka-sim-chasy-panel.md), [T-106](T-106-zhivaya-trassirovka-agenta.md), [T-108](T-108-lenta-izmenenij-bd-schetchiki-tablic-prosmotr-st.md), [T-119](T-119-lending-potencialnogo-klienta-antibot-proverka-q.md), [T-130](T-130-ui-benchmarkov.md), [T-133](T-133-ekran-kalkulyator-poter-dopuscheniya-v-stile-biz.md), [T-177](T-177-ekran-feed-emulyator-lenty-ploschadki-vidzhet-ab.md), [T-182](T-182-zahvat-audio-v-brauzere-getusermedia-audioworkle.md), [T-188](T-188-ekran-manager-emulyator-plansheta-i-smart-chasov.md)

## Что сделать
1. Vite + React 18 + TS strict + Tailwind; tokens.css: палитра (#21A038, градиент → #0098F8, #F1E813, статусные цвета), радиусы, тени, типографика; темы dark/light/circadian (по фазе симуляции).
2. Шрифты Inter и JetBrains Mono — файлы в public/fonts (OFL), @font-face.
3. Роутинг (react-router): /setup, /, /incidents/:id, /hitl, /engine, /bench, /settings, /landing, /track/:token, /economics.
4. react-i18next с ru.json/en.json, переключатель языка и темы в шапке, формат дат/чисел через Intl.
5. Базовые компоненты: Button, Badge (критичность/статус), Card, Table, Drawer, Tabs, Toast, Skeleton; обе темы соответствуют контрасту ≥ 4.5:1.

## Критерии приёмки
- [ ] `npm run build` без предупреждений, нет внешних URL в dist (тест test_no_cdn).
- [ ] Переключение темы/языка без перезагрузки.
- [ ] Скриншоты базовых компонентов в обеих темах приложены к PR.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
cd frontend && npm run lint && npm run build
pytest backend/tests/integration/test_no_cdn.py
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
