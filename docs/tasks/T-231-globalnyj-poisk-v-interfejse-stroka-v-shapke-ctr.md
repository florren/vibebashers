# T-231 — Глобальный поиск в интерфейсе: строка в шапке, Ctrl+K, чипы типов, результаты по группам, <IdLink> для всех идентификаторов

| Поле | Значение |
|---|---|
| Эпик | E23 Поиск и след объекта [АРХ] |
| Субагент | `SA-UI-Trace` (экраны «Путь обращения» и «Поиск и след» [АРХ]) |
| Оценка | M (1–2 дня) |
| Волна | 8 |
| Слой | `L4` Фронт (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `todo` |

## Цель
Пользователь попадает на след объекта из любого места интерфейса (ТЗ 28.1, 28.5).

## Разделы ТЗ (docs/TZ.md)
§28.1, §28.5, §26.4

## Контракты
- `api/openapi.yaml: GET /api/search`
- frontend/src/shared/components/IdLink
- frontend/src/shared/components/GlobalSearch

## Зависимости
- Зависит от: [T-230](T-230-universalnyj-poisk-app-search-raspoznavanie-iden.md), [T-086](T-086-layout-rabochego-mesta-cx-shapka-sim-chasy-panel.md)
- Блокирует: [T-232](T-232-ekran-sled-trace-kind-ref-do-obekt-posle-itog-oz.md)

## Что сделать
1. `GlobalSearch`: строка в шапке и палитра по `/` и `Ctrl+K`, определение типа на лету (чип «SIG», «INC», «CL» …), недавние запросы, результаты по группам с превью и клавиатурной навигацией, переход на `/trace/:kind/:ref`.
2. `IdLink`: единый компонент отображения и ссылки идентификатора (копирование, подсказка типа, переход на след, `aria-label`); заменить ручной вывод идентификаторов в `SignalDrawer`, карточке инцидента, тикетнице, ленте `/feed`, очереди HITL, эскалациях, `/compliance`, `/manager`.
3. Состояния: загрузка, пусто («Ничего не нашли по … — проверьте код, он выглядит как `SIG-000123`»), неоднозначно (выбор кандидата), ошибка без обвинения; i18n ru/en.
4. vitest на разбор ввода и навигацию клавишами; e2e: поиск по `SIG`, `INC`, `CL`, числу.

## Критерии приёмки
- [ ] Любой идентификатор в перечисленных экранах — кликабельная ссылка на след.
- [ ] Поиск открывается с клавиатуры, управляется стрелками и Enter; фокус и контраст соответствуют правилам.
- [ ] Нет внешних запросов и шрифтов (`test_no_cdn`).
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
cd frontend && npx vitest run src/shared/components
cd frontend && npx playwright test e2e/global-search.spec.ts
```

## Отчёт субагента
GlobalSearch в шапке: /, Ctrl+K, чипы SIG/INC/CL, группы, стрелки/Enter, состояния ошибок/пустого/неоднозначного результата. IdLink с копированием и подсказкой подключён к SignalDrawer, инцидентам, тикетнице, HITL, feed, compliance, manager и задачам. ru/en и тесты навигации.

Ветка: `codex/journey-trace`; пакет T-224/T-231/T-232/T-225/T-230/T-226/T-233. `cross-layer` согласован пользователем. Контракты T-223 и механизм денег/HITL не изменялись.

Проверки: `make lint`, `make test` (461 unit / 86 integration / 22 scenario passed; 20 skipped), contracts, OpenAPI drift, owners --allow-cross и i18n — успешно. Новые backend-пакеты: coverage 94% (43 targeted tests). Frontend: typecheck, lint, build, 39 vitest и 4 Playwright — успешно. Скриншоты ru/en × light/dark: `docs/screenshots/trace-journey/`. Локальная тестовая PostgreSQL 18.6 с UTC; PostgreSQL 16 проверяется CI. Node 26 требует `NODE_OPTIONS=--no-experimental-webstorage` для существующих jsdom-тестов; CI использует Node 22.

Сценарии 12/13 добавлены как YAML-манифесты модели чтения; проверки сценариев 1/8/11 на записанных mock-данных и отдельный replay сценария 8 проходят. Эти YAML не создают новый запуск агента из UI. Новый live-прогон GigaChat не выполнялся. Полная приёмка дополнительных требований карточек за пределами указанного пользователем среза не заявляется.
